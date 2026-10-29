"""Single-file runner tests: all modes execute existing engine; zero network/keys."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import socket
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from docx import Document
import optimize_resume as cli
from modules.ai import resume_optimizer as engine
from modules.job_pipeline.http import FetchError
from test_resume_pipeline import synthetic_source,mocked_convert,api_response


class SingleFileResumeCLITest(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.source=self.root/'resume.docx'
        synthetic_source(self.source);mocked_convert(str(self.source),str(self.source.with_suffix('.pdf')))
        self.jd=self.root/'jd.txt';self.jd.write_text('Python AWS Kubernetes full exact responsibilities and qualifications')
        self.config={'optimization_mode':'skills','replace_job_title':False,'expected_page_count':1,
            'project_bullet_banks':[],'max_skills':50,'layout_retry':False}
        self.original=self.source.read_bytes()
        self.network=patch.object(socket.socket,'connect',side_effect=AssertionError('NETWORK FORBIDDEN'));self.network.start();self.addCleanup(self.network.stop)

    def args(self,*extra,output='run'):
        return cli.parser().parse_args(['--resume',str(self.source),'--jd-file',str(self.jd),'--job-title','Principal Engineer',
            '--output',str(self.root/output),*extra])

    def optimizer(self):
        opt=engine.ResumeOptimizer.__new__(engine.ResumeOptimizer);opt.client=Mock()
        opt.client.chat.completions.create.return_value=api_response('{"keywords":["Python","AWS","Kubernetes"]}')
        opt.convert_docx_to_pdf=Mock(side_effect=mocked_convert)
        opt._call_openai_to_rewrite_bullets=Mock(side_effect=lambda entries,*args:[dict(e,bullets=[b.replace('using','with').replace('Improved','Enhanced') for b in e['bullets']]) for e in entries])
        return opt

    def run_offline(self,args,opt=None):
        with redirect_stdout(io.StringIO()),patch.object(engine,'load_dotenv',side_effect=AssertionError('No credential loading')),patch.object(cli,'configured_optimizer',side_effect=AssertionError('No credential loading')):
            code=cli.execute(args,optimizer_instance=opt or self.optimizer(),runtime_config_override=self.config,execution_kind='offline_fixture')
        return code,json.loads((args.output/'run-summary.json').read_text())

    def test_all_modes_and_independent_title_overrides_use_existing_engine(self):
        for mode in ('skills','bullets','full'):
            for replace in (False,True):
                with self.subTest(mode=mode,replace=replace):
                    args=self.args('--mode',mode,'--replace-title' if replace else '--no-replace-title',output=f'{mode}-{replace}')
                    opt=self.optimizer();code,summary=self.run_offline(args,opt)
                    self.assertEqual(code,0);self.assertFalse(summary['generated_attachment_eligible'])
                    self.assertEqual(summary['mode'],mode);self.assertEqual(summary['replace_title'],replace)
                    self.assertEqual(summary['provider_calls'],0)
                    pdf=Path(summary['preview_pdf']);self.assertTrue(pdf.exists())
                    doc=Document(pdf.with_suffix('.docx'));text='\n'.join(p.text for p in doc.paragraphs)
                    self.assertEqual('Principal Engineer\t' in text,replace)
                    self.assertEqual('Built production services with Python' in text,mode!='skills')
                    self.assertEqual(opt._call_openai_to_rewrite_bullets.call_count,int(mode!='skills'))
                    self.assertEqual(self.source.read_bytes(),self.original)
                    opt.client.close.assert_called_once()

    def test_preflight_defaults_and_flags_never_load_key_or_engine(self):
        for mode in ('skills','bullets','full'):
            args=self.args('--mode',mode,'--preflight',output='pre-'+mode)
            with patch.object(cli,'configured_optimizer',side_effect=AssertionError('key forbidden')),patch.object(engine,'run_resume_optimization',side_effect=AssertionError('engine forbidden')),redirect_stdout(io.StringIO()) as out:
                self.assertEqual(cli.execute(args,runtime_config_override=self.config),0)
            plan=json.loads(out.getvalue());self.assertFalse(plan['credentials_read'])
            self.assertEqual(plan['replace_title'],mode=='full');self.assertFalse(args.output.exists())

    def test_inline_and_file_jd_preserve_exact_text(self):
        text='Complete JD\nPython and AWS\nRequired: Kubernetes\n'
        args=self.args();args.jd_file=None;args.jd_text=text
        self.assertEqual(cli.load_jd(args)[0],text)
        self.jd.write_text(text);args.jd_file=self.jd;args.jd_text=None
        self.assertEqual(cli.load_jd(args)[0],text)
        args.jd_file=None;args.jd_text='https://example.com/job'
        with self.assertRaises(ValueError):cli.load_jd(args)

    def test_public_jsonld_url_reuses_bounded_fetch_and_full_description(self):
        args=self.args();args.jd_file=None;args.jd_url='https://example.com/jobs/123'
        html='<html><script type="application/ld+json">'+json.dumps({'@type':'JobPosting','title':'Principal Engineer',
            'description':'<p>Complete Python role.</p><h2>Requirements</h2><p>AWS &amp; Kubernetes</p>'})+'</script></html>'
        client=Mock();client.get.return_value=SimpleNamespace(status_code=200,url=args.jd_url,text=html)
        text,meta=cli.load_jd(args,client)
        self.assertEqual(text,'Complete Python role. Requirements AWS & Kubernetes')
        self.assertEqual(meta['jd_sha256'],cli.digest(text));client.get.assert_called_once_with(args.jd_url,timeout=12)

    def test_unsupported_ambiguous_restricted_or_private_urls_fail_closed(self):
        args=self.args();args.jd_file=None
        for url,html,status in [('http://127.0.0.1/job','',200),('https://example.com/jobs','<p>JavaScript only</p>',200),
            ('https://example.com/job','captcha challenge',200),('https://example.com/job','',403),
            ('https://example.com/jobs','<script type="application/ld+json">'+json.dumps([{'@type':'JobPosting','description':'one'},{'@type':'JobPosting','description':'two'}])+'</script>',200)]:
            with self.subTest(url=url,status=status):
                args.jd_url=url;client=Mock();client.get.return_value=SimpleNamespace(status_code=status,url=url,text=html)
                with self.assertRaises((ValueError,FetchError)):cli.load_jd(args,client)

    def test_rejects_output_overwrite_pdf_bullets_and_incompatible_scope_before_credentials(self):
        args=self.args();args.output.mkdir()
        with self.assertRaises(ValueError):cli.plan(args,runtime_config_override=self.config)
        for extra in (('--mode','skills','--rewrite-all-bullets'),):
            with self.assertRaises(ValueError):cli.plan(self.args(*extra,output='invalid'),runtime_config_override=self.config)
        args=self.args('--mode','bullets',output='pdf');args.resume=self.source.with_suffix('.pdf')
        with self.assertRaises(ValueError):cli.plan(args,runtime_config_override=self.config)
        args=self.args('--mode','skills','--no-replace-title','--preflight',output='pdf-skills');args.resume=self.source.with_suffix('.pdf')
        with redirect_stdout(io.StringIO()):self.assertEqual(cli.execute(args,runtime_config_override=self.config),0)

    def test_none_result_stays_partial_preview_never_promoted(self):
        args=self.args('--rewrite-all-bullets')
        def partial(*args,**kwargs):
            out=Path(kwargs['output_root']);out.mkdir()
            (out/'optimized.pdf').write_bytes(b'partial')
            (out/'match-report.json').write_text(json.dumps({'status':'partial','output_path':str(out/'optimized.pdf'),
                'rewrite_completed':False,'strict_attachment_eligible':False,'format_verification':{'passed':False}}))
            return None
        with patch.object(engine,'run_resume_optimization',side_effect=partial),redirect_stdout(io.StringIO()):
            self.assertEqual(cli.execute(args,optimizer_instance=self.optimizer(),runtime_config_override=self.config),2)
        summary=json.loads((args.output/'run-summary.json').read_text())
        self.assertIsNone(summary['optimized_pdf']);self.assertFalse(summary['generated_attachment_eligible'])
        self.assertTrue(summary['preview_pdf']);self.assertEqual(summary['status'],'partial_or_blocked')

    def test_client_config_and_output_injection_do_not_mutate_saved_config(self):
        args=self.args('--mode','skills');original=dict(self.config)
        with patch.object(engine,'load_runtime_config',side_effect=AssertionError('saved config access forbidden')):
            code,summary=self.run_offline(args)
        self.assertEqual(code,0);self.assertEqual(self.config,original)
        self.assertTrue(Path(summary['preview_pdf']).is_relative_to(args.output.resolve()/'review'))


    def test_strict_engine_receives_injected_client_and_output_without_credentials(self):
        opt=self.optimizer();options=dict(self.config,rewrite_all_bullets=True)
        with patch.object(engine,'load_dotenv',side_effect=AssertionError('key forbidden')),patch('modules.resume_all_bullets.run_all_bullets',return_value=None) as strict:
            result=engine.run_resume_optimization('Python complete JD',str(self.source),'strict','Engineer',optimization_mode='bullets',
                runtime_config_override=options,optimizer_instance=opt,output_root=str(self.root/'strict'))
        self.assertIsNone(result)
        self.assertEqual(strict.call_args.kwargs['output_root'],str(self.root/'strict'))
        self.assertTrue(callable(strict.call_args.kwargs['provider']))
        opt.client.with_options.return_value.chat.completions.create.return_value='response'
        self.assertEqual(strict.call_args.kwargs['provider']('keywords',{'job_description':'Python complete JD'},3),'response')
        opt.client.with_options.assert_called_once_with(timeout=3,max_retries=0)
        call=opt.client.with_options.return_value.chat.completions.create.call_args.kwargs
        self.assertEqual(call['response_format']['type'],'json_schema')

    def test_missing_credential_records_blocked_without_exposing_exception_body(self):
        args=self.args('--mode','skills')
        with patch.object(cli,'configured_optimizer',side_effect=ValueError('private detail not copied')),redirect_stdout(io.StringIO()):
            with self.assertRaises(ValueError):cli.execute(args,runtime_config_override=self.config)
        summary=(args.output/'run-summary.json').read_text()
        self.assertNotIn('private detail',summary);self.assertEqual(json.loads(summary)['status'],'blocked')

    def url_args(self,title=None,output='url-run',mode='skills'):
        args=self.args('--mode',mode,'--no-replace-title',output=output)
        args.jd_file=None;args.jd_url='https://example.com/jobs/123';args.job_title=title
        return args

    def url_client(self,postings):
        client=Mock();client.get.return_value=SimpleNamespace(status_code=200,url='https://example.com/jobs/123',
            text='<html><title>Generic company careers</title><script type="application/ld+json">'+json.dumps(postings)+'</script></html>')
        return client

    def title_reply(self,title='Principal Engineer',spans=None,status='extracted'):
        return {'status':status,'title':title,'evidence_spans':spans if spans is not None else ['Principal Engineer'],'reason':'Supported target role in complete JD'}

    def title_optimizer(self,value=None,error=None):
        opt=self.optimizer();create=opt.client.with_options.return_value.chat.completions.create
        if error:create.side_effect=error
        else:create.return_value=SimpleNamespace(id='mock-title-response',usage=SimpleNamespace(model_dump=lambda:{'prompt_tokens':100,'completion_tokens':40}),
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(value or self.title_reply())))])
        return opt

    def test_optional_title_preflight_reports_ai_needed_for_every_missing_input_type(self):
        cases=[('--jd-file',str(self.jd),None),('--jd-text','Looking for a Principal Engineer',None),
            ('--jd-url','https://example.com/jobs/123',{'@type':'JobPosting','description':'Principal Engineer role'}),
            ('--jd-url','https://example.com/jobs/123',{'@type':'JobPosting','title':['One','Two'],'description':'Principal Engineer role'})]
        for flag,value,posting in cases:
            with self.subTest(input=flag,posting=posting):
                args=cli.parser().parse_args(['--resume',str(self.source),flag,value,'--output',str(self.root/'no-title'),'--preflight'])
                with patch.object(cli,'configured_optimizer',side_effect=AssertionError('key forbidden')),patch.object(engine,'run_resume_optimization',side_effect=AssertionError('engine forbidden')),redirect_stdout(io.StringIO()) as out:
                    self.assertEqual(cli.execute(args,client=self.url_client(posting) if posting else None,runtime_config_override=self.config),0)
                value=json.loads(out.getvalue());self.assertEqual(value['status'],'preflight_requires_ai_title')
                self.assertIsNone(value['job_title']);self.assertEqual(value['job_title_source'],'ai_extraction_required')
                self.assertTrue(value['title_extraction_needed']);self.assertFalse(value['credentials_read']);self.assertEqual(value['provider_calls'],0)
                self.assertFalse(args.output.exists())

    def test_explicit_title_wins_all_input_types_without_ai_title_call(self):
        for kind in ('file','text','url'):
            args=self.args('--mode','skills',output='explicit-'+kind);args.job_title=' Explicit Target '
            if kind=='text':args.jd_file=None;args.jd_text='Principal Engineer in prose'
            if kind=='url':args.jd_file=None;args.jd_url='https://example.com/jobs/123'
            posting={'@type':'JobPosting','title':'Different Structured Title','description':'Complete Python role'}
            with patch.object(cli,'extract_title',side_effect=AssertionError('No title AI allowed')),redirect_stdout(io.StringIO()):
                code=cli.execute(args,client=self.url_client(posting) if kind=='url' else None,optimizer_instance=self.optimizer(),runtime_config_override=self.config,execution_kind='offline_fixture')
            self.assertEqual(code,0)
            value=json.loads((args.output/'run-summary.json').read_text());self.assertEqual(value['job_title'],'Explicit Target');self.assertEqual(value['job_title_source'],'explicit_job_title')

    def test_structured_title_fallback_precedes_ai_and_is_used_by_engine(self):
        posting={'@type':'JobPosting','title':'Software Engineer - Inference Platform','description':'Complete Python AWS role'}
        args=self.url_args(output='structured-execute')
        with patch.object(cli,'extract_title',side_effect=AssertionError('No title AI allowed')),redirect_stdout(io.StringIO()):
            code=cli.execute(args,client=self.url_client(posting),optimizer_instance=self.optimizer(),runtime_config_override=self.config,execution_kind='offline_fixture')
        self.assertEqual(code,0)
        summary=json.loads((args.output/'run-summary.json').read_text());provenance=json.loads((args.output/'input-provenance.json').read_text())
        report=json.loads(Path(summary['report_path']).read_text())
        for value in (summary,provenance):
            self.assertEqual(value['job_title'],posting['title']);self.assertEqual(value['job_title_source'],'structured_jobposting')
        self.assertEqual(report['job_title'],posting['title']);self.assertFalse(summary['replace_title'])

    def test_ai_fallback_continues_for_text_file_missing_or_ambiguous_url_title(self):
        jd='Looking for a Principal Engineer to build Python AWS services. FULL JD CONTEXT'
        self.jd.write_text(jd)
        for index,kind in enumerate(('file','text','url-missing','url-blank','url-ambiguous')):
            args=self.args('--mode','skills','--no-replace-title',output='ai-'+str(index));args.job_title=None;client=None
            if kind=='text':args.jd_file=None;args.jd_text=jd
            if kind.startswith('url'):
                args.jd_file=None;args.jd_url='https://example.com/jobs/123'
                title=None if kind=='url-missing' else '' if kind=='url-blank' else ['One Title','Other Title']
                client=self.url_client({'@type':'JobPosting','title':title,'description':jd})
            opt=self.title_optimizer()
            with redirect_stdout(io.StringIO()),patch.object(engine,'load_dotenv',side_effect=AssertionError('No keys')):
                self.assertEqual(cli.execute(args,client=client,optimizer_instance=opt,runtime_config_override=self.config,execution_kind='offline_fixture'),0)
            summary=json.loads((args.output/'run-summary.json').read_text());event=json.loads((args.output/'title-extraction.json').read_text())
            self.assertEqual(summary['job_title'],'Principal Engineer');self.assertEqual(summary['job_title_source'],'ai_extraction')
            self.assertEqual(json.loads(Path(summary['report_path']).read_text())['job_title'],'Principal Engineer')
            self.assertEqual(event['response_id'],'mock-title-response');self.assertEqual(event['execution_kind'],'offline_fixture')
            call=opt.client.with_options.return_value.chat.completions.create.call_args.kwargs
            self.assertEqual(json.loads(call['messages'][1]['content'])['job_description'],jd)
            self.assertEqual(call['response_format']['type'],'json_schema');opt.client.with_options.assert_called_once_with(timeout=45,max_retries=0)
            self.assertEqual(summary['provider_calls'],0);self.assertFalse(summary['replace_title']);self.assertFalse(summary['generated_attachment_eligible'])

    def test_title_extraction_uses_configured_reasoning_model_options(self):
        opt=self.title_optimizer()
        config={**self.config,'rewrite_model':'gpt-6-luna','rewrite_reasoning_effort':'none',
            'rewrite_max_output_tokens':6000}
        title,_=cli.extract_title('Looking for a Principal Engineer to build services.',config,opt,'offline_fixture')
        self.assertEqual(title,'Principal Engineer')
        call=opt.client.with_options.return_value.chat.completions.create.call_args.kwargs
        self.assertEqual(call['model'],'gpt-6-luna')
        self.assertEqual(call['extra_body'],{'reasoning_effort':'none'})
        self.assertEqual(call['max_completion_tokens'],700)
        self.assertNotIn('max_tokens',call)

    def test_blank_explicit_title_uses_structured_then_ai_instead_of_stopping(self):
        posting={'@type':'JobPosting','title':'Valid Structured Title','description':'Principal Engineer role'}
        self.assertEqual(cli.plan(self.url_args(' \t\n '),self.url_client(posting),self.config)[4]['job_title_source'],'structured_jobposting')
        args=self.args();args.job_title=''
        self.assertEqual(cli.plan(args,runtime_config_override=self.config)[4]['job_title_source'],'ai_extraction_required')

    def test_ai_response_validation_rejects_unsupported_seniority_and_nonexact_evidence(self):
        jd='We need a Principal Engineer for Python services.'
        values=[self.title_reply('Staff Engineer'),self.title_reply('Principal Engineer',['not in JD']),
            self.title_reply(''),self.title_reply('Principal\nEngineer'),self.title_reply(None,status='unsupported'),
            self.title_reply(None,status='ambiguous'),{'title':'Principal Engineer'},
            dict(self.title_reply(),unexpected='field')]
        for value in values:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):cli.validate_extracted_title(value,jd)
        self.assertEqual(cli.validate_extracted_title(self.title_reply(),jd),'Principal Engineer')
        self.assertEqual(cli.validate_extracted_title(self.title_reply('Distributed Systems Engineer',['distributed systems engineers']),
            'Looking for distributed systems engineers'),'Distributed Systems Engineer')

    def test_invalid_ai_or_provider_failure_is_actionable_and_never_starts_optimizer(self):
        self.jd.write_text('Principal Engineer role using Python')
        for index,opt in enumerate((self.title_optimizer(self.title_reply('Invented Chief Engineer')),self.title_optimizer(error=RuntimeError('PRIVATE_PROVIDER_ERROR_BODY')))):
            args=self.args('--mode','skills',output='bad-ai-'+str(index));args.job_title=None
            with patch.object(engine,'run_resume_optimization',side_effect=AssertionError('Resume engine must not start')),redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(cli.TitleExtractionError,'pass --job-title'):cli.execute(args,optimizer_instance=opt,runtime_config_override=self.config,execution_kind='offline_fixture')
            summary=json.loads((args.output/'run-summary.json').read_text());event=(args.output/'title-extraction.json').read_text()
            self.assertEqual(summary['status'],'blocked');self.assertFalse(summary['generated_attachment_eligible'])
            self.assertNotIn('PRIVATE_PROVIDER_ERROR_BODY',event);opt.client.close.assert_called_once()
        opt=self.title_optimizer();opt.client.with_options.return_value.chat.completions.create.return_value.choices[0].message.content='not JSON'
        with self.assertRaises(cli.TitleExtractionError):cli.extract_title('Principal Engineer role',self.config,opt,'offline_fixture')

    def test_multiple_postings_and_generic_page_title_never_choose_unrelated_jd(self):
        for explicit in (None,'Matching Title'):
            postings=[{'@type':'JobPosting','title':'Matching Title','description':'Python role'},
                {'@type':'JobPosting','title':'Other Title'}]
            with self.assertRaisesRegex(ValueError,'exactly one unambiguous JobPosting'):
                cli.plan(self.url_args(explicit),self.url_client(postings),self.config)
        posting={'@type':'JobPosting','description':'Principal Engineer role'}
        details=cli.plan(self.url_args(),self.url_client(posting),self.config)[4]
        self.assertIsNone(details['job_title']);self.assertTrue(details['title_extraction_needed'])

    def test_title_request_debits_strict_global_cost_request_and_time_allowance(self):
        self.jd.write_text('Principal Engineer role using Python')
        args=self.args('--rewrite-all-bullets',output='strict-ai');args.job_title=None;opt=self.title_optimizer()
        def no_result(*args,**kwargs):
            config=kwargs['runtime_config_override']
            self.assertLess(config['rewrite_max_cost_usd'],2);self.assertEqual(config['rewrite_max_requests'],99)
            self.assertLess(config['rewrite_run_timeout'],300);self.assertEqual(args[3],'Principal Engineer')
            return None
        with patch.object(engine,'run_resume_optimization',side_effect=no_result),redirect_stdout(io.StringIO()):
            self.assertEqual(cli.execute(args,optimizer_instance=opt,runtime_config_override=self.config,execution_kind='offline_fixture'),2)


    def test_cancelled_title_attempt_is_recorded_before_resume_engine(self):
        self.jd.write_text('Principal Engineer role using Python')
        args=self.args('--mode','skills',output='cancel-title');args.job_title=None
        opt=self.title_optimizer(error=KeyboardInterrupt())
        with patch.object(engine,'run_resume_optimization',side_effect=AssertionError('Resume engine must not start')),redirect_stdout(io.StringIO()):
            with self.assertRaises(cli.TitleExtractionCancelled):cli.execute(args,optimizer_instance=opt,runtime_config_override=self.config,execution_kind='offline_fixture')
        event=json.loads((args.output/'title-extraction.json').read_text());summary=json.loads((args.output/'run-summary.json').read_text())
        self.assertEqual(event['request_attempts'],1);self.assertEqual(event['status'],'cancelled')
        self.assertEqual(summary['status'],'cancelled');self.assertFalse(summary['generated_attachment_eligible'])
        opt.client.close.assert_called_once()
