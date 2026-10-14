# LinkedIn AI Auto Job Applier 🤖
This is a web scraping bot that automates the process of job applications on LinkedIn. It searches for jobs relevant to you, answers application questions from your configured profile, customizes the resume using job information, and can submit Easy Apply applications. The bot can process many applications quickly, but it should be run with a submission pause enabled until the answers and resume output have been reviewed.


## 📽️ See it in Action
Click on above image to watch the demo or use this link https://youtu.be/gMbB1fWZDHw


## ✨ Content
- [Introduction](#linkedin-ai-auto-job-applier-)
- [Demo Video](#-see-it-in-action)
- [Index](#-content)
- [Install](#-how-to-install)
- [Current workflow](#current-workflow)
- [Repository map](#repository-map)
- [Run commands](#run-commands)
- [Configure](#-how-to-configure)
- [Resume ATS optimizer](#resume-ats-optimizer)
- [Detailed documentation](docs/README.md)
- [Troubleshooting](#troubleshooting)
- [Dynamic Search Profiles](#dynamic-search-profiles)
- [Contributor Guidelines](#-contributor-guidelines)
- [Features](#-feature-list)
- [My letter for YOU ❤️](#-my-heartfelt-letter-to-you-)
- [Updates](#major-updates-history)
- [Disclaimer](#-disclaimer)
- [Terms and Conditions](#-terms-and-conditions)
- [License](#-license)
- [Socials](#-socials)
- [Support and Discussions](#community-support-and-discussions)

<br>

## Current workflow

The repository has two related workflows:

1. `runAiBot.py` drives the LinkedIn browser session. It searches using the values in `config/search.py`, filters jobs, reads the job and company information, answers Easy Apply questions from `config/questions.py` and `config/personals.py`, uploads the configured resume, and records the result in the CSV history files and `logs/`.
2. `JobRobo.py` opens the desktop dashboard. The **Run LinkedIn Bot** action loads and starts the browser automation. The **Resume Optimizer** tab saves optimizer settings and runs the ATS pipeline without starting Chrome.

For a DOCX resume in `bullets` or `full` mode, the optimizer follows this sequence:

```text
Job description
      ↓
Existing keyword extraction + skills-bank guidance
      ↓
Skills section update
      ↓
JD-aware bullet rewrite for ordinary professional experience
      ↓
Exact, curated bullet-bank selection for Trek Health and the first three projects
      ↓
Optional job-title alignment (`full` mode)
      ↓
DOCX → PDF conversion → configured page-count/layout verification
      ↓
Accepted PDF + `.match_report.json` (or failure report)
```

The optimizer and the LinkedIn bot are intentionally separate. You can generate and inspect a resume without starting Chrome, and you can use a static resume by running the bot without enabling resume optimization. A browser run can submit applications, so keep `pause_before_submit = True` while validating a new configuration.

## Repository map

| Path | Responsibility |
| --- | --- |
| `runAiBot.py` | Main LinkedIn automation entry point. |
| `JobRobo.py` | Tkinter dashboard for browser automation and resume optimization. |
| `config/search.py` | Search terms, location, filters, quotas, and skip rules. |
| `config/questions.py` | Application answers, resume paths, pause behavior, salary, visa, and profile inputs. |
| `config/personals.py` | Personal information used in application forms. |
| `config/settings.py` | Browser, timing, safe mode, stealth mode, logging, and legacy resume flags. |
| `config/resume_optimizer_defaults.json` | Persistent optimizer mode, bank paths, page-count expectation, and runtime defaults. |
| `modules/ai/resume_optimizer.py` | Keyword guidance, skills optimization, bullet rewriting, bank selection, PDF/DOCX handling, and format verification. |
| `modules/resume_upload.py` | Optimized-PDF attachment and independently verified source-PDF fallback. |
| `config/skills/` | ATS vocabulary and role-profile guidance. |
| `config/bullets/` | Fact-preserving bullet banks for specific companies and projects. |
| `all resumes/default/` | Default DOCX/PDF resume uploaded by the bot. |
| `all resumes/temp/` | Generated, job-specific resumes and match reports. |
| `all excels/` | Applied and failed application history CSVs. |
| `logs/` | Runtime logs and failure screenshots. |
| `tests/` | Automated tests for the resume optimizer and format contract. |
| `docs/` | In-depth architecture, optimizer reference, ATS guidance, role positioning, and developer runbook. |

See the [documentation index](docs/README.md) for the tutorial, architecture explanation, configuration reference, ATS workflow, staff/principal positioning guide, current market notes, and maintenance runbook.

## Run commands

From the repository root, create an isolated environment and install the dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate              # macOS/Linux
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Run the automated checks before changing the live application configuration:

```bash
python -m py_compile modules/ai/resume_optimizer.py modules/config_loader.py JobRobo.py
python -m json.tool config/resume_optimizer_defaults.json >/dev/null
python -m unittest discover -s tests -v
```

Start the browser automation only after Chrome is closed or the dedicated JobRobo profile is configured:

```bash
python runAiBot.py
```

Open the dashboard when you want to configure and run the optimizer interactively:

```bash
python JobRobo.py
```

DOCX optimization requires LibreOffice in addition to Python dependencies. The converter checks `LIBREOFFICE_PATH`, `soffice` / `libreoffice` on `PATH`, and the macOS application path. All optimizer modes require an OpenAI API key for JD keyword extraction.

The optimizer can also be called from Python without opening the dashboard. Repository defaults fill missing fields in the saved user configuration at `~/Library/Application Support/jobrobo/config/resume_optimizer_defaults.json`; existing user choices remain authoritative:

```python
from modules.ai.resume_optimizer import run_resume_optimization

output_path = run_resume_optimization(
    job_description="Staff AI platform engineer building secure LLM inference systems",
    resume_path="all resumes/default/resume.docx",
    job_id="local-smoke-test",
    job_title="Staff AI Platform Engineer",
    first_name="first",
    last_name="last",
    optimization_mode="skills",
)
print(output_path)
```

Use `optimization_mode="skills"` to update Skills only, `"bullets"` to update Skills and bullets, or `"full"` to also replace recognized professional-experience titles with the target title. `full` does not rewrite the summary or validate title equivalence. Use a distinct local job ID and inspect the returned PDF and report before an application run.

## ⚙️ How to install
1. [Python 3.10](https://www.python.org/) or above. Visit https://www.python.org/downloads/ to download and install Python, or for windows you could visit Microsoft Store and search for "Python". **Please make sure Python is added to Path in System Environment Variables**.
2. Install the pinned Python dependencies from `requirements.txt`. After Python is installed, open a console/terminal or shell and use the [pip](https://pip.pypa.io/en/stable) command-line tool:
  ```
  python -m pip install -r requirements.txt
  ```
3. Download and install latest version of [Google Chrome](https://www.google.com/chrome) in it's default location, visit https://www.google.com/chrome to download it's installer.
4. Clone the current git repo or download it as a zip file, then run commands from the repository root.
5. If `stealth_mode = False`, install the ChromeDriver build matching your Chrome major version. See [Chrome for Testing](https://googlechromelabs.github.io/chrome-for-testing/) for downloads. If `stealth_mode = True`, `undetected-chromedriver` downloads a driver at runtime, but startup is less predictable and requires network access.
  <br> <br>
  ***OR*** 
  <br> <br>
  If you are using Windows, click on `windows-setup.bat` available in the `/setup` folder, this will install the latest chromedriver automatically.
6. If you have questions or need help setting it up or to talk in general, join the github server: https://discord.gg/fFp7uUzWCY

[back to index](#-content)

<br>

## 🔧 How to configure
1. Open `personals.py` file in `/config` folder and enter your details like name, phone number, address, etc. Whatever you want to fill in your applications.
2. Open `questions.py` file in `/config` folder and enter your answers for application questions, configure wether you want the bot to pause before submission or pause if it can't answer unknown questions.
3. Open `search.py` file in `/config` folder and enter your search preferences, job filters, configure the bot as per your needs (these settings decide which jobs to apply for or skip). Configure role lanes, skills, and manual searches in `search_profile.py`; location and filter values remain in `search.py`. See [Dynamic Search Profiles](docs/dynamic-search.md).
4. Prefer environment variables or a local, uncommitted secrets configuration for LinkedIn/OpenAI credentials. Credentials are optional: if no LinkedIn username/password is supplied, the bot uses the configured Chrome profile and asks for manual login when needed. Never commit real credentials to `config/secrets.py`.
5. Open `settings.py` file in `/config` folder to configure the bot settings like, keep screen awake, click intervals (click intervals are randomized to seem like human behavior), run in background, stealth mode (to avoid bot detection), etc. as per your needs.
6. Add the default resume paths in `config/questions.py`: `default_resume_path` for a static upload and `default_resume_docx_path` for DOCX optimization. With AI optimization enabled, keep a current sibling PDF beside the DOCX: if optimization fails, the bot independently verifies and explicitly attaches that PDF. If neither attachment succeeds, it discards the application before Review/Submit.
7. Run `runAiBot.py` and see the magic happen.
8. If you have questions or need help setting it up or to talk in general, join the github server: https://discord.gg/fFp7uUzWCY

### Configuration reference

| File or setting | What it controls | Typical first-run value |
| --- | --- | --- |
| `config/search.py:search_terms` | LinkedIn search queries. | `['Senior Software Engineer']` |
| `config/search.py:search_location` | Location entered into LinkedIn search. | `'California, United States'` |
| `config/search.py:switch_number` | Applications processed before moving to the next search. | `1` for a smoke test |
| `config/settings.py:run_in_background` | Whether Chrome is visible. | `False` while debugging |
| `config/settings.py:safe_mode` | Opens a clean Guest-style browser profile when normal Chrome startup fails. | `True` for startup troubleshooting |
| `config/settings.py:chrome_profile_path` | Dedicated Chrome user-data directory used by JobRobo. | Leave the macOS default or set an absolute path |
| `config/questions.py:pause_before_submit` | Pauses before the final submit action. | `True` until answers are verified |
| `config/questions.py:pause_at_failed_question` | Pauses when an unknown question cannot be answered. | `True` |
| `config/questions.py:default_resume_path` | PDF uploaded to LinkedIn. | `all resumes/default/resume.pdf` |
| `config/questions.py:default_resume_docx_path` | DOCX source used when resume optimization is enabled. | `all resumes/default/resume.docx` |
| `config/resume_optimizer_defaults.json:optimization_mode` | Resume rewrite scope. | `skills`, `bullets`, or `full` |

Keep secrets out of commits. Use environment variables or the repository's existing key-loader flow for OpenAI credentials, and do not paste real passwords into documentation, issues, or screenshots. If a credential has ever been committed, rotate it before continuing.

### Safe first run

Use this sequence before allowing unattended applications:

1. Use one search term and set `switch_number = 1`, `run_non_stop = False`, `run_in_background = False`, `pause_before_submit = True`, and `pause_at_failed_question = True`. The quota is per search term, not per run.
2. Close extra Chrome windows and tabs. A large number of open tabs can cause ChromeDriver to start a browser without reaching the job page.
3. Run the test suite and inspect the configured resume paths.
4. Start `python runAiBot.py`, review the job, answers, attached resume, and final submission screen.
5. Stop the run manually if it proceeds to another job unexpectedly. Multiple search terms can each process their quota even with non-stop looping disabled. Increase quotas or enable repeated cycling only after the one-job path is understood.

### Resume ATS optimizer

The optimizer keeps the existing job-description keyword extraction flow and adds
curated vocabulary guidance from
`config/skills/Skills_Keyword_Bank_Staff_Principal_2026-10.md`. The job description
is still authoritative: bank suggestions must match JD vocabulary, while the selected
role profile helps rank those matches.

Configure the mode in the GUI or saved user JSON. The bundled `config/resume_optimizer_defaults.json` supplies defaults for missing fields:

```json
"optimization_mode": "full"
```

Valid modes are:

| Mode | Changes | Use when |
| --- | --- | --- |
| `skills` | Reorders and replaces the Skills section only. | Existing bullets already fit the role, or the source is a PDF. |
| `bullets` | Updates Skills, rewrites ordinary experience, and inserts exact bank bullets into matching entries. | You want JD alignment while preserving titles. |
| `full` | Runs `bullets` plus recognized professional-experience title replacement. | You have reviewed the accuracy of the title changes. |

Bullet and title operations require DOCX. PDF input always uses Skills-only editing
and records `effective_mode: "skills-pdf"`. The optimizer
does not rewrite the summary or change project titles.

#### Skill guidance and JD context

The flow extracts keywords from the JD, infers a role profile such as Staff / Principal
AI Platform or Healthcare AI, and combines those results with the existing Skills
section. The same selected skills and JD-guided phrases are passed to the bullet
rewrite prompt. The model is instructed to preserve facts, but the implementation
does not independently validate work history. Skills-bank terms marked `†` are allowed
by default; set `allow_unverified_bank_terms` to `false` to filter those bank suggestions.
Extracted JD terms still require human review for evidence.

Skills selection prioritizes JD guidance and deduplicates recognized full-phrase/acronym
pairs such as `Model Context Protocol (MCP)` and `MCP`. The original number of entries
is an upper bound; duplicates can shrink the result. DOCX edits reuse source runs and
their font/character spacing to preserve compact template formatting.

#### Curated bullet banks

Configured project bullet banks in `config/bullets/` provide exact, JD-ranked bullets
for the first matching company entry. The default configuration covers:

| Resume entry | Bank | Default selection |
| --- | --- | ---: |
| `TREK HEALTH` | `Trek_Health_Bullet_Bank.md` | 7 bullets, including platform and leadership sections |
| `CODEX SELF-HOSTED` | `Codex_SelfHosted_Bullet_Bank.md` | 3–5 bullets, always including Platform |
| `SOHAMHAMSO` | `Sohamhamso_Bullet_Bank.md` | 2–4 bullets, always including Overview |
| `SPONSORSKIP` | `SponsorSkip_Bullet_Bank.md` | 1–2 bullets, always including Overview |

The three project banks target named entries under `ENTREPRENEURIAL VENTURES & PROJECTS`;
matching uses company/project text and the expected paragraph structure, not project order.
For each bank, the selector scores preset references, JD lookup phrases, direct JD
word overlap, and preferred character length. It applies maximum counts, category
targets, metric/verb deduplication, and marker exclusions. Minimum counts and required
categories can be unmet when too few eligible candidates remain. Bullets marked `†` or `‡` are
excluded by default because they require candidate proof or confirmation. Set a bank's
`allow_unverified` value to `true` only after reviewing its evidence. Unmarked bank
text is not independently fact-checked by the optimizer.

The exact bank bullet replaces the first matching entry's existing list paragraphs.
All other professional-experience entries continue through the existing JD-aware LLM
rewrite path. A `skills` run does not rewrite bullets or apply bullet banks.

Example project-bank configuration:

```json
"project_bullet_banks": [
  {
    "path": "config/bullets/Codex_SelfHosted_Bullet_Bank.md",
    "company": "CODEX SELF-HOSTED",
    "min_bullets": 3,
    "max_bullets": 5,
    "required_sections": ["A"],
    "allow_unverified": false
  }
]
```

#### Output and verification

Generated files are written under the resume's sibling `temp/` directory with a
job-specific filename. The optimizer also writes a `.match_report.json` beside the
intended PDF containing requested/normalized/effective modes, status, attempt history,
keywords, bank IDs, `pre_optimization` / `post_optimization` keyword coverage, and
format-verification results. Keyword coverage is a local diagnostic, not an ATS vendor score.

The post-conversion verifier rejects output when it does not meet the configured
contract. The default expects two pages, extractable text, horizontal/vertical text
bounds, source-relative sections and rendered headings, no new orphaned headings,
stable bullet counts, and similar margins/body font sizes. DOCX/PDF consistency also
requires at least 95% normalized token coverage and every DOCX section heading in
rendered order. Wrapping details remain inspection
signals; a pass does not establish identical appearance or truthful claims.

A failed `bullets`/`full` DOCX verification receives one Skills-only retry from the source.
If accepted, it records `effective_mode: "skills-fallback"`, with empty top-level bank
selections; rejected choices and checks remain in `attempts`. If no optimized artifact is
accepted, the bot can attach an independently verified source PDF. If both upload paths
fail, the application is discarded before Review/Submit. A previous LinkedIn attachment
is not accepted as fallback success. See the [reference](docs/resume-optimizer-reference.md)
for the complete configuration and report contract.

[back to index](#-content)

<br>

## Troubleshooting

### Chrome opens and immediately exits

This usually means ChromeDriver cannot create a compatible session, Chrome is
already holding the selected profile, or the browser profile has stale startup
state. Try these checks in order:

1. Close every Chrome window and confirm no Chrome process is still running.
2. Check that Chrome and ChromeDriver major versions match. Update Chrome and use
   the matching driver from [Chrome for Testing](https://googlechromelabs.github.io/chrome-for-testing/).
3. Set `safe_mode = True` in `config/settings.py` and retry. Safe mode uses a clean
   profile rather than the everyday Chrome profile.
4. If `stealth_mode = True`, reinstall the package in the active environment:

   ```bash
   python -m pip uninstall undetected-chromedriver
   python -m pip install undetected-chromedriver
   ```

5. Keep the browser visible with `run_in_background = False` while diagnosing. Do
   not debug startup failures with a large batch or unattended submission enabled.

### The browser starts but does not reach the job

Close excess tabs before starting. The bot expects to control the active JobRobo
profile and can appear idle when Chrome opens with another profile or too many tabs.
Check `chrome_profile_path`, confirm LinkedIn is logged in to that profile, and run
with `pause_after_filters = True` if you need to inspect the search state.

### The bot continues to another job

`switch_number` controls the quota for each search term. For a one-job smoke test,
use one term, set `switch_number = 1`, keep `run_non_stop = False`, and leave
`pause_before_submit = True`. If a run has already
submitted the expected application, stop it manually before changing the quota or
cycling settings.

### Resume optimization fails or produces the wrong output

Check that the DOCX and PDF source paths exist, the DOCX contains a standalone
`SKILLS` heading or an inline `Skills:` section, and the OpenAI key is available to
the active Python environment. Run the unit tests before retrying. Then inspect the
generated `.match_report.json`; it records keyword coverage, selected bank IDs, and
the attempt and format check that failed. Early API or conversion errors can produce
failure reports without an accepted PDF. Check the returned path and `status` before
using any artifact from the output folder.

### Generated resume is not two pages

The default verifier expects two pages because the current resume template is a
two-page document. Use `skills` mode first, reduce the configured skill count, or
shorten unsupported source content. Do not bypass the verifier merely to submit a
longer document: the bot's upload path is intended to use a verified PDF.

[back to index](#-content)

<br>

## Dynamic Search Profiles

Searches combine enabled manual queries from `config/search_profile.py`, existing `search_terms`, and queries generated from your role lanes and skills. Each query uses the current location, filters, and exclusion settings in `config/search.py`. The existing San Francisco Bay Area, full-time, remote/hybrid preferences and Staff/Principal search terms are preserved. Duplicate queries keep the first definition, with manual searches taking precedence.

`dynamic_search_enabled = True` and `ai_query_refinement_enabled = True` are enabled by default. Search refinement uses OpenAI independently of resume optimization and `use_AI`; missing credentials or invalid responses fall back to deterministic role queries. `use_AI_for_resume = True` is configured for the next run. `switch_number = 1` sets the default per-search smoke quota, and `pause_before_submit = True` remains enabled.

The runner attempts LinkedIn's natural-language search, records the actual search mode and any fallback or filter warnings, and saves query checkpoints under `logs/search_runs/`. A matching interrupted run resumes automatically; completed searches and previously submitted jobs are skipped. Submission checkpoints across all saved runs also protect fresh runs when CSV logging failed; uncertain submissions remain skipped for manual inspection. Applied and failed CSV records include the run, query, mode, profile, and source. Existing CSV rows are preserved during header migration.

See the [configuration, resume behavior, and verification guide](docs/dynamic-search.md) for manual-search examples, safe query previews, and the limits of the classic keyword fallback. Implementation verification uses automated tests; no live applications were submitted for verification.

[back to index](#-content)

<br>


## 🧑‍💻 Contributor Guidelines
Thank you for your efforts and being a part of the community. All contributions are appreciated no matter how small or big. Once you contribute to the code base, your work will be remembered forever.

NOTE: Only Pull request to `community-version` branch will be accepted. Any other requests will be declined by default, especially to main branch.
Once your code is tested, your changes will be merged to the `main` branch in next cycle.

### Code Guidelines
  #### Functions:
  1. All functions or methods are named lower case and snake case
  2. Must have explanation of their purpose. Write explanation surrounded in `''' Explanation '''` under the definition `def function() -> None:`. Example:
      ```python
      def function() -> None:
        '''
        This function does nothing, it's just an example for explanation placement!
        '''
      ```
  4. The Types `(str, list, int, list[str], int | float)` for the parameters and returns must be given. Example:
      ```python
      def function(param1: str, param2: list[str], param3: int) -> str:
      ```
  5. Putting all that together some valid examples for function or method declarations would be as follows.
      ```python
      def function_name_in_camel_case(parameter1: driver, parameter2: str) -> list[str] | ValueError:
        '''
        This function is an example for code guidelines
        '''
        return [parameter2, parameter2.lower()]
      ```
  6. The hashtag comments on top of functions are optional, which are intended for developers `# Comments for developers`.
      ```python
      # Enter input text function
      def text_input_by_ID(driver: WebDriver, id: str, value: str, time: float=5.0) -> None | Exception:
          '''
          Enters `value` into the input field with the given `id` if found, else throws NotFoundException.
          - `time` is the max time to wait for the element to be found.
          '''
          username_field = WebDriverWait(driver, time).until(EC.presence_of_element_located((By.ID, id)))
          username_field.send_keys(Keys.CONTROL + "a")
          username_field.send_keys(value)
      
      ```
   
  #### Variables
  1. All variables must start with lower case, must be in explainable full words. If someone reads the variable name, it should be easy to understand what the variable stores.
  2. All local variables are camel case. Examples:
      ```python
      jobListingsElement = None
      ```
      ```python
      localBufferTime = 5.5
      ```
  3. All global variables are snake case. Example:
      ```
      total_runs = 1
      ```
  4. Mentioning types are optional.
      ```python
      localBufferTime: float | int = 5.5
      ```
  
  #### Configuration variables
  1. All config variables are treated as global variables. They have some extra guidelines.
  2. Must have variable setting explanation, and examples of valid values. Examples:
      ```python
      # Explanation of what this setting will do, and instructions to enter it correctly
      config_variable = "value1"    #  <Valid values examples, and NOTES> "value1", "value2", etc. Don't forget quotes ("")
      ```
      ```python
      # Do you want to randomize the search order for search_terms?
      randomize_search_order = False     # True of False, Note: True or False are case-sensitive
      ```
      ```python
      # Avoid applying to jobs if their required experience is above your current_experience. (Set value as -1 if you want to apply to all ignoring their required experience...)
      current_experience = 5             # Integers > -2 (Ex: -1, 0, 1, 2, 3, 4...)
      ```
      ```python
      # Search location, this will be filled in "City, state, or zip code" search box. If left empty as "", tool will not fill it.
      search_location = "United States"               # Some valid examples: "", "United States", "India", "Chicago, Illinois, United States", "90001, Los Angeles, California, United States", "Bengaluru, Karnataka, India", etc.

      ```
  4. Add the config variable in appropriate `/config/file`.
  5. Every config variable must be validated. Go to `/modules/validator.py` and add it over there. Example:
      For config variable `search_location = ""` found in `/config/search.py`, string validation is added in file `/modules/validator.py` under the method `def validate_search()`.
      ```python
      def validate_search() -> None | ValueError | TypeError:
          '''
          Validates all variables in the `/config/search.py` file.
          '''
          check_string(search_location, "search_location")
      ```

  [back to index](#-content)
  
  ### Attestation
  1. All contributions require proper attestion. Format for attestation:
  ```python
  ##> ------ <Your full name> : <github id> OR <email> - <Type of change> ------
      print("My contributions 😍") # Your code
  ##<
  ```
  2. Examples for proper attestation:
  New feature example
  ```python
  def alert_box(title: str, message: str) -> None:
    '''
    Shows an alert box with the given `title` and `message`.
    '''
    from pyautogui import alert
    return alert(title, message)

  ##<
  ```
  
  Bug fix example
  ```python
  def alert_box(title: str, message: str) -> None:
    '''
    Shows an alert box with the given `title` and `message`.
    '''
    from pyautogui import alert

    return alert(message, title)
  ##<
  ```

[back to index](#-content)

<br>

## 🤩 Feature List
The list below separates the working browser/application path from experimental or
legacy paths. Some LinkedIn page changes can still require manual intervention.

#### General Features 🚀:

- Opens browser with default logged in google account (Yet to test with browsers having multiple profiles)
- **Auto Login**: If configured or already saved in browser (not saved passwords)
- Apply filters (Salary, Companies, Experience Level,... ) Must config
- Region specific searches
- Opens job search and searches key words
- Easy applies
- Auto Answers questions answered in config
- Collects urls of career page if have to Apply externally
- Collects HR Info
- Collects skills required (In Development)
- Collects experience required and skips if not applicable to you, must be configured
- Auto Filters jobs based on your experience and black list key words
- Skips blacklisted jobs
- Can be configured to skip jobs requiring Security Clearance
- You can add exceptions to blacklist key words
- Only applies to filtered jobs
- Auto selects next pages until it hits the quota you configured
- Selects your default resume
- Auto Submits
- Saves all the info of applied jobs, failed to apply jobs in excels and logs
- Takes screenshot of questions answered to fail, for future debugging
- Saves info of all questions, it's options, previous answer and current answer in application
- Option to overwrite previous answers
- Continuous applications non stop (beta)
- No need for fear of missing out, Goes through all possible filters and sorts combinations with each cycle if configured (Most Recent, Most Relevant, Newest First, Past 24 Hrs, Past Month, Past Week etc)
- Option to randomize the search order
- Run in background, headless browser
- Auto collects a looooooooooooooooooot of info about your jobs, check applied-jobs.excel and failed_jobs.excel for info after each run.
- Optional pause before submit application.
- Optional pause if stuck at a question.
- Configurable ATS resume optimization with `skills`, `bullets`, and `full` modes.
- JD-guided skill selection from the Staff / Principal keyword bank.
- Curated, fact-preserving bullet banks for Trek Health, Codex Self-Hosted, Sohamhamso, and SponsorSkip.
- Post-conversion resume verification for page count, text extraction, section order, clipping, and layout similarity.
- JSON match reports with keyword coverage, verification results, and failed/accepted attempt history.




#### Stealth features 🥸🤫:  
- Optional undetected ChromeDriver integration. Chrome and ChromeDriver major versions must remain compatible.
- Click intervals can be randomized and increased to avoid suspicions
- Smooth Scrolls the elements into view before click

#### Upcoming Features or currently in development 🤖🛠️:
- Answer questions with help of chatGpt or other LLMs
- Humanize clicks and mouse movements for stealth 
- Auto send personalized messages to HR that accept messages
- Broader resume generation beyond the current DOCX/PDF optimizer
- Additional browser-supported application question strategies

#### Currently Broken 🥲😭: 
- Legacy browser-based ChatGPT login and resume chat-window integration. The current
  optimizer uses the configured OpenAI API/key-loader path instead.
      
[back to index](#-content)

<br>




## ✉️ My Heartfelt letter to you ❤️...

My Dear User,

Thank you for using the job application tool! Your support means everything to me. 

As you continue your job search, I hope this tool has provided you with valuable assistance and streamlined your efforts.

To continue improving and maintaining this tool, I rely on the support of users like you. If you believe in its mission and want to contribute, you can support me by sharing about this project with your peers and network.

By doing so, you can empower others in their job hunt, just as you've been empowered.. Every contribution, big or small, makes a significant impact!

As an independent developer, I pour my heart and soul into creating tools like this, driven by the genuine desire to make a positive impact. Your support, whether through donations or simply spreading the word, means the world to me and helps keep this project alive and thriving.

You can connect and reach me out at:
- LinkedIn  :  https://www.linkedin.com/in/dannybasavaraju/
- Email     :  danny.basavaraju@gmail.com

<br>

Thank you for being part of this journey, and remember that together, we can make a real difference in the lives of job seekers worldwide.

With heartfelt appreciation, <br>

<br>
<br>

[back to index](#-content)

<br>

## Major Updates History

### October 12, 2026
- Added configurable ATS optimization modes: Skills-only, bullet rewrite, and full title alignment.
- Added JD-guided skill-bank vocabulary and shared JD context for bullet rewriting.
- Added exact, safe-claim bullet-bank selection for Trek Health and the first three entrepreneurial projects.
- Added two-page/layout verification and JSON match reports before optimized resumes are accepted.
- Added documentation and tests for Chrome profile troubleshooting, resume output verification, and project-bank configuration.

### Nov 28, 2024
- Patched to work for latest changes in Linkedin.
- Users can now select to follow or not follow companies when submitting application.
- Frameworks for future AI Developments have been added.
- AI can now be used to extract skills from job description. 

### Oct 16, 2024
- Framework for OpenAI API and Local LLMs
- Framework for RAG

### Sep 09, 2024
- Smarter Auto-fill for salaries and notice periods
- Robust Search location filter, will work in window mode (No need for full screen)
- Better logic for Select and Radio type questions
- Proper functioning of Decline to answer questions in Equal Employment opportunity questions
- Checkbox questions select fail bug fixed
- Annotations are clearer in instructions for setup

### Sep 07, 2024
- Annotations for developers
- Robust input validations
- Restructured config file
- Fixed pagination bug

### Aug 21, 2024
- Performance improvements (skip clicking on applied jobs and blacklisted companies)
- Stop when easy apply application limit is reached
- Added ability to discard from pause at submission dialogue box
- Added support for address input
- Bug fixed radio questions, added support for physical disability questions
- Added framework for future config file updates

### June 19, 2024
- Major Bug fixes (Text Area type questions)
- Made uploading default resume as not required

### May 15, 2024
- Added functionality for textarea type questions `summary`, `cover_letter`(Summary, Cover letter); checkbox type questions (acknowledgements)
- Added feature to skip irrelevant jobs based on `bad_words` 
- Improved performance for answering questions
- Logic change for masters students skipping
- Change variable names `blacklist_exceptions` -> `about_company_good_words` and `blacklist_words` -> `about_company_bad_words`
- Added session summary for logs
- Added option to turn off "Pause before Submit" until next run

### May 05, 2024
- For questions similar to "What is your current location?", City posted in Job description will be posted as the answer if `current_city` is left empty in the configuration
- Added option to over write previously saved answers for a question `overwrite_previous_answers`
- Tool will now save previous answer of a question
- Tool will now collect all available options for a Radio type or Select type question
- Major update in answering logic for Easy Apply Application questions
- Added Safe mode option for quick stable launches `safe_mode`

### May 04, 2024
- Added option to fill in "City, state, or zip code" search box `search_location`
- Bug fixes in answering City or location question


[back to index](#-content)

<br>

## 📜 Disclaimer

**This program is for educational purposes only. By downloading, using, copying, replicating, or interacting with this program or its code, you acknowledge and agree to abide by all the Terms, Conditions, Policies, and Licenses mentioned, which are subject to modification without prior notice. The responsibility of staying informed of any changes or updates bears upon yourself. Additionally, kindly adhere to and comply with LinkedIn's terms of service and policies pertaining to web scraping. Usage is at your own risk. The creators and contributors of this program emphasize that they bear no responsibility or liability for any misuse, damages, or legal consequences resulting from its usage.**


## 🏛️ Terms and Conditions

Please consider the following:

- **LinkedIn Policies**: LinkedIn has specific policies regarding web scraping and data collection. The responsibility to review and comply with these policies before engaging, interacting, or undertaking any actions with this program bears upon yourself. Be aware of the limitations and restrictions imposed by LinkedIn to avoid any potential violation(s).

- **No Warranties or Guarantees**: This program is provided as-is, without any warranties or guarantees of any kind. The accuracy, reliability, and effectiveness of the program cannot be guaranteed. Use it at your own risk.

- **Disclaimer of Liability**: The creators and contributors of this program shall not be held responsible or liable for any damages or consequences arising from the direct or indirect use, interaction, or actions performed with this program. This includes but is not limited to any legal issues, loss of data, or other damages incurred.

- **Use at Your Own Risk**: It is important to exercise caution and ensure that your usage, interactions, and actions with this program comply with the applicable laws and regulations. Understand the potential risks and consequences associated with web scraping and data collection activities.

- **Chrome Driver**: This program utilizes the Chrome Driver for web scraping. Please review and comply with the terms and conditions specified for [Chrome Driver](https://chromedriver.chromium.org/home).


## ⚖️ License

This program is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License along with this program. If not, see <https://www.gnu.org/licenses/>.

See [AGPLv3 LICENSE](LICENSE) for more info.


<br>

[back to index](#-content)

<br>

## Community support and discussions

Use the [GitHub repository](https://github.com/deepakb66/jobrobo) for reproducible
bugs, configuration questions, and patches. Include your operating system, Python
version, Chrome version, ChromeDriver mode, optimization mode, and the relevant
sanitized log excerpt. Never include LinkedIn credentials, API keys, application
answers containing personal data, or full screenshots with private information.

For setup discussion and community help, join the project's Discord server:
https://discord.gg/fFp7uUzWCY

[back to index](#-content)

<br>

## 🐧 Socials
- **LinkedIn** : https://www.linkedin.com/in/dannybasavaraju/
- **Email**    : danny.basavaraju@gmail.com
- **X/Twitter**: https://x.com/deepakcool3


#### ℹ️ Version: [0.1.1.0](VERSION)

---

[back to the top](#linkedin-ai-auto-job-applier-)
