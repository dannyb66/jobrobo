"""Preferred first-name override replaces controlled fields and preserves other identity."""
import ast,re
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
from test_search_runner import extract_functions,MissingElement,RUNNER

class PreferredNameTests(unittest.TestCase):
    def setup_field(self,label,preferred='Alex',revert=False):
        field=Mock();field.value='Example' if 'last' in label.lower() else 'Sam';field.selected=False
        def send(*keys):
            if keys in (('\ue03d','a'),('\ue009','a')):field.selected=True
            elif keys==('\ue003',) and field.selected:field.value='';field.selected=False
            elif keys==('\ue004',):
                if revert:field.value='Reverted'
            else:field.value+=''.join(keys)
        field.clear.side_effect=lambda:None
        field.send_keys.side_effect=send;field.get_attribute.side_effect=lambda name:field.value
        heading=Mock();heading.text=label;heading.find_element.side_effect=MissingElement()
        question=Mock();modal=Mock();modal.find_elements.return_value=[question]
        def locate(target,xpath,*args):
            if target is question:
                if xpath==".//input[@type='text']":return field
                if xpath=='.//label[@for]':return heading
            return False
        class Wait:
            def until(self,check):
                if not check(None):raise MissingElement('Exact input value not retained after blur')
                return True
        ns={'re':re,'By':SimpleNamespace(XPATH='xpath',CLASS_NAME='class'),'try_xp':locate,'driver':Mock(),
            'Keys':SimpleNamespace(COMMAND='\ue03d',CONTROL='\ue009',BACKSPACE='\ue003',TAB='\ue004'),'WebDriverWait':lambda *a:Wait(),
            'overwrite_previous_answers':False,'preferred_first_name':preferred,'first_name':'Alex','last_name':'Example','middle_name':'','full_name':'Alex Example'}
        names=['answer_questions']
        if any(isinstance(n,ast.FunctionDef) and n.name=='replace_text_verified' for n in ast.parse(RUNNER.read_text()).body):names.append('replace_text_verified')
        extract_functions(ns,*names)
        return field,lambda:ns['answer_questions'](modal,set(),'San Francisco Bay Area')
    def test_prefilled_ordinary_first_name_is_replaced_exactly(self):
        for label in ('First name','First name*','Preferred first name'):
            with self.subTest(label=label):
                field,answer=self.setup_field(label);answer();self.assertEqual(field.value,'Alex')
    def test_repeated_fill_is_idempotent_and_cannot_concatenate(self):
        field,answer=self.setup_field('First name');answer();answer();self.assertEqual(field.value,'Alex')
    def test_react_reversion_after_blur_blocks_completion(self):
        field,answer=self.setup_field('First name',revert=True)
        with self.assertRaises(MissingElement):answer()
    def test_existing_legal_and_other_identity_fields_are_preserved(self):
        for label in ('Legal first name','Legal name','Last name','Full name','Signature','Middle name'):
            with self.subTest(label=label):
                field,answer=self.setup_field(label);before=field.value;answer();self.assertEqual(field.value,before);field.send_keys.assert_not_called()
    def test_absent_preference_preserves_existing_value(self):
        field,answer=self.setup_field('First name',preferred='');answer();self.assertEqual(field.value,'Sam');field.send_keys.assert_not_called()
