"""LinkedIn bot and shared pipeline entry point. Importing does not start a browser."""
from __future__ import annotations

import os
import re
from random import choice, shuffle, randint
from datetime import datetime
from typing import Literal

from config import search_profile
from modules.search_planner import build_search_plan
from modules.search_state import SearchManifest, plan_fingerprint
from modules.search_history import append_history, load_applied_job_ids, search_metadata, file_lock
from modules.linkedin_search import (
    start_search, prepare_search, apply_configured_filters, AI_INPUT_XPATH,
    get_search_cards, search_card_id, read_search_card, search_results_ready,
    get_search_pagination, next_search_page,
)
from modules.ai.search_refinement import make_refiner
from modules.application_budget import ApplicationBudget

_runtime_loaded = False
_apply_credentials_loaded = False
driver = wait = actions = None
_browser_background = None
active_manifest = active_search = None
active_page = 1
active_result_sink = None
active_application_budget = None
current_pipeline_blocked_ids = set()
aiClient = None


def initialize_browser(*, background=None):
    global driver, wait, actions, _browser_background
    if driver is not None:
        try:
            reusable = bool(driver.window_handles) and not (background is False and _browser_background is True)
        except Exception:
            reusable = False
        if not reusable:
            try:
                driver.quit()
            except Exception:
                pass
            driver = wait = actions = None
    if driver is None:
        from modules.open_chrome import create_browser
        driver, wait, actions = create_browser(background=background)
        _browser_background = globals().get("run_in_background", False) if background is None else background
    return driver


def _export_runtime_module(name):
    import importlib
    module = importlib.import_module(name)
    globals().update({key: value for key, value in vars(module).items() if not key.startswith("_")})


def load_runtime(execution_mode="apply"):
    global _runtime_loaded, _apply_credentials_loaded
    global AI_INPUT_XPATH, By, EC, ElementClickInterceptedException, ElementNotInteractableException, Literal, NoSuchElementException, NoSuchWindowException, ResumeUploadError, SearchManifest, Select, WebDriverWait, WebElement, about_company_for_ai, active_manifest, active_page, active_search, aiClient, append_history, apply_configured_filters, build_search_plan, choice, current_ctc, current_ctc_lakhs, current_ctc_monthly, dailyEasyApplyLimitReached, datetime, desired_salary, desired_salary_lakhs, desired_salary_monthly, easy_applied_count, external_jobs_count, failed_count, file_lock, first_name, full_name, last_name, llm_api_key, load_applied_job_ids, load_dotenv, load_openai_key, make_refiner, middle_name, notice_period, notice_period_months, notice_period_weeks, os, password, pause_at_failed_question, pause_before_submit, plan_fingerprint, pyautogui, randint, randomly_answered_questions, re, re_experience, run_non_stop, run_resume_optimization, search_metadata, search_profile, shuffle, skip_count, start_search, tabs_count, upload_verified_resume, useNewResume, use_AI, use_AI_for_resume, username, validate_config
    if _runtime_loaded:
        if execution_mode != "search" and not _apply_credentials_loaded:
            load_openai_key()
            globals()["llm_api_key"] = os.getenv("OPENAI_API_KEY") or globals().get("llm_api_key")
            _apply_credentials_loaded = True
        return
    import os
    import re
    import pyautogui
    from random import choice, shuffle, randint
    from datetime import datetime
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support.select import Select
    from selenium.webdriver.remote.webelement import WebElement
    from selenium.common.exceptions import NoSuchElementException, ElementClickInterceptedException, NoSuchWindowException, ElementNotInteractableException
    _export_runtime_module("config.personals")
    _export_runtime_module("config.questions")
    _export_runtime_module("config.search")
    from config.secrets import use_AI, use_AI_for_resume, username, password
    _export_runtime_module("config.settings")
    _export_runtime_module("modules.helpers")
    _export_runtime_module("modules.clickers_and_finders")
    from modules.validator import validate_config
    _export_runtime_module("modules.ai.openaiConnections")
    from typing import Literal
    from dotenv import load_dotenv
    from modules.ai.resume_optimizer import run_resume_optimization
    from modules.resume_upload import ResumeUploadError, upload_verified_resume
    from modules.ai.openai_key_loader import load_openai_key
    from config import search_profile
    from modules.search_planner import build_search_plan
    from modules.search_state import SearchManifest, plan_fingerprint
    from modules.search_history import append_history, load_applied_job_ids, search_metadata, file_lock
    from modules.linkedin_search import start_search, apply_configured_filters, AI_INPUT_XPATH
    from modules.ai.search_refinement import make_refiner
    pyautogui.FAILSAFE = False
    if execution_mode != "search":
        load_openai_key()
        _apply_credentials_loaded = True
    llm_api_key = os.getenv("OPENAI_API_KEY") or globals().get("llm_api_key")
    if run_in_background == True:
        pause_at_failed_question = False
        pause_before_submit = False
        run_non_stop = False
    first_name = first_name.strip()
    middle_name = middle_name.strip()
    last_name = last_name.strip()
    full_name = first_name + " " + middle_name + " " + last_name if middle_name else first_name + " " + last_name
    useNewResume = True
    randomly_answered_questions = set()
    tabs_count = 1
    easy_applied_count = 0
    external_jobs_count = 0
    failed_count = 0
    skip_count = 0
    dailyEasyApplyLimitReached = False
    re_experience = re.compile(r'[(]?\s*(\d+)\s*[)]?\s*[-to]*\s*\d*[+]*\s*year[s]?', re.IGNORECASE)
    desired_salary_lakhs = str(round(desired_salary / 100000, 2))
    desired_salary_monthly = str(round(desired_salary/12, 2))
    desired_salary = str(desired_salary)
    current_ctc_lakhs = str(round(current_ctc / 100000, 2))
    current_ctc_monthly = str(round(current_ctc/12, 2))
    current_ctc = str(current_ctc)
    notice_period_months = str(notice_period//30)
    notice_period_weeks = str(notice_period//7)
    notice_period = str(notice_period)
    aiClient = None
    active_manifest = None
    active_search = None
    active_page = 1
    about_company_for_ai = None
    _runtime_loaded = True

#< Login Functions
def is_logged_in_LN() -> bool:
    '''
    Function to check if user is logged-in in LinkedIn
    * Returns: `True` if user is logged-in or `False` if not
    '''
    if driver.current_url == "https://www.linkedin.com/feed/": return True
    if try_linkText(driver, "Sign in"): return False
    if try_xp(driver, '//button[@type="submit" and contains(text(), "Sign in")]'):  return False
    if try_linkText(driver, "Join now"): return False
    print_lg("Didn't find Sign in link, so assuming user is logged in!")
    return True


def login_LN() -> None:
    '''
    Function to login for LinkedIn
    * Tries to login using given `username` and `password` from `secrets.py`
    * If failed, tries to login using saved LinkedIn profile button if available
    * If both failed, asks user to login manually
    '''
    # Find the username and password fields and fill them with user credentials
    driver.get("https://www.linkedin.com/login")
    try:
        wait.until(EC.presence_of_element_located((By.LINK_TEXT, "Forgot password?")))
        try:
            text_input_by_ID(driver, "username", username, 1)
        except Exception as e:
            print_lg("Couldn't find username field.")
            # print_lg(e)
        try:
            text_input_by_ID(driver, "password", password, 1)
        except Exception as e:
            print_lg("Couldn't find password field.")
            # print_lg(e)
        # Find the login submit button and click it
        driver.find_element(By.XPATH, '//button[@type="submit" and contains(text(), "Sign in")]').click()
    except Exception as e1:
        try:
            profile_button = find_by_class(driver, "profile__details")
            profile_button.click()
        except Exception as e2:
            # print_lg(e1, e2)
            print_lg("Couldn't Login!")

    try:
        # Wait until successful redirect, indicating successful login
        wait.until(EC.url_to_be("https://www.linkedin.com/feed/")) # wait.until(EC.presence_of_element_located((By.XPATH, '//button[normalize-space(.)="Start a post"]')))
        return print_lg("Login successful!")
    except Exception as e:
        print_lg("Seems like login attempt failed! Possibly due to wrong credentials or already logged in! Try logging in manually!")
        # print_lg(e)
        manual_login_retry(is_logged_in_LN, 2)
#>



def get_applied_job_ids() -> set:
    '''
    Function to get a `set` of applied job's Job IDs
    * Returns a set of Job IDs from existing applied jobs history csv file
    '''
    return (load_applied_job_ids(file_name) | SearchManifest.applied_ids(search_profile.search_state_dir)
            | globals().get("current_pipeline_blocked_ids", set()))



def set_search_location(location=None):
    """Commit the configured geographic suggestion; text alone is insufficient."""
    from modules.linkedin_search import select_search_location
    location = globals().get("search_location", "") if location is None else location
    if location.strip():
        print_lg(f'Setting search location as: "{location.strip()}"')
    return select_search_location(driver, location, wait_for_search_results)


def apply_filters(spec) -> list[str]:
    """Apply available controls independently and record unsupported preferences."""
    from modules.linkedin_search import LocationSelectionError, verify_search_location
    warnings = []
    confirmation = None
    location = spec.filters_snapshot["intent"].get("search_location") or ""
    if location:
        try:
            confirmation = set_search_location(location)
        except LocationSelectionError as error:
            if spec.mode == "classic":
                raise
            warnings.append(f"Location filter unavailable in AI mode: {error}; checking each job's location before applying")
    try:
        button = driver.find_element(By.XPATH, '//button[normalize-space()="All filters"]')
        button.click()
        buffer(1)
    except NoSuchElementException:
        warnings.append("All filters unavailable; attempting visible search filters")

    def xpath_literal(value):
        if '"' not in value:
            return '"' + value + '"'
        if "'" not in value:
            return "'" + value + "'"
        return "concat(" + ", '\"', ".join('"' + part + '"' for part in value.split('"')) + ")"

    def select_option(key, value):
        literal = xpath_literal(value)
        if key in {"easy_apply_only", "under_10_applicants", "in_your_network", "fair_chance_employer"}:
            controls = driver.find_elements(By.XPATH, f'.//h3[normalize-space()={literal}]/ancestor::fieldset//input[@role="switch"]')
            if controls:
                control = controls[0]
                if not control.is_selected():
                    scroll_to_view(driver, control)
                    actions.move_to_element(control).click().perform()
                return True
        matches = driver.find_elements(By.XPATH, f'.//label[normalize-space(.)={literal}] | .//span[normalize-space(.)={literal}]')
        for element in matches:
            if not element.is_displayed():
                continue
            controls = element.find_elements(By.XPATH, 'ancestor-or-self::label//input | ancestor::fieldset//input[@role="switch"]')
            if controls and controls[0].is_selected():
                return True
            scroll_to_view(driver, element)
            element.click()
            return True
        if key == "companies":
            company_search_click(driver, actions, value)
            # The dynamic picker must actually expose the requested company.
            return bool(driver.find_elements(By.XPATH, f'.//label[contains(., {literal})]'))
        return False

    warnings.extend(apply_configured_filters(spec.filters_snapshot["intent"], select_option))
    buttons = driver.find_elements(By.XPATH, '//button[contains(@aria-label, "Apply current filters to show") or normalize-space()="Show results"]')
    if buttons:
        buttons[0].click()
    else:
        try_xp(driver, './/button[@aria-label="Dismiss"]')

    if confirmation is not None:
        verify_search_location(driver, confirmation)

    global pause_after_filters
    if pause_after_filters and "Turn off Pause after search" == pyautogui.confirm("These are your configured search results and filters. You can modify them while this dialog is open.", "Please check your results", ["Turn off Pause after search", "Look's good, Continue"]):
        pause_after_filters = False
    return warnings


def wait_for_search():
    from modules.linkedin_modern_search import find_prompt
    WebDriverWait(driver, 10).until(lambda browser: find_prompt(browser) is not None
                                  or search_results_ready(browser)
                                  or browser.find_elements(By.XPATH, '//input[contains(@id, "jobs-search-box-keyword")]'))


def wait_for_search_results(previous):
    # Modern LinkedIn reuses card nodes across queries; DOM staleness is not a
    # reliable completion signal. The adapter verifies the submitted query and
    # filters, then waits for a recognized list or an explicit empty state.
    WebDriverWait(driver, 15).until(search_results_ready)


def checkpoint_job(job_id, status, reason=None):
    if active_manifest and active_search:
        budget = globals().get("active_application_budget")
        if budget is not None:
            if status == "applied":
                # Confirmation already happened remotely. A failed disk write
                # must never reopen a submission slot in this invocation.
                budget.record(job_id)
            active_manifest.data["invocation_applied_count"] = budget.count
        active_manifest.record_job(active_search, job_id, status, reason, active_page)
        if globals().get("active_result_sink"):
            active_result_sink(application_outcome(active_manifest, active_search, job_id))



def get_page_info() -> tuple[WebElement | None, int | None]:
    '''
    Function to get pagination element and current page number
    '''
    return get_search_pagination(driver)



def get_job_main_details(job: WebElement, blacklisted_companies: set, rejected_jobs: set, *, read_only=False) -> tuple[str, str, str, str, str, bool]:
    '''
    # Function to get job main details.
    Returns a tuple of (job_id, title, company, work_location, work_style, skip)
    * job_id: Job ID
    * title: Job title
    * company: Company name
    * work_location: Work location of this job
    * work_style: Work style of this job (Remote, On-site, Hybrid)
    * skip: A boolean flag to skip this job
    '''
    if not job.get_dom_attribute('data-occludable-job-id'):
        details = read_search_card(job)
        job_id, title, company = details['id'], details['title'], details['company']
        work_location, work_style = details['location'], details['workplace_type']
        if not job_id or not title or not company:
            raise ValueError("Modern job card lacks a verifiable ID, title, or employer")
        skip = company in blacklisted_companies or job_id in rejected_jobs
        if not skip:
            anchor = details.get('title_element')
            if anchor is None:
                anchors = job.find_elements(By.CSS_SELECTOR, "a[href*='/jobs/view/']")
                anchor = next((element for element in anchors
                               if str(search_card_id(element)) == str(job_id)), None)
            if anchor is None:
                raise ValueError("Modern job card has no matching LinkedIn job link")
            scroll_to_view(driver, anchor, True)
            anchor.click()
            from modules.linkedin_job_details import modern_details_ready
            live = WebDriverWait(driver, 15).until(lambda browser: modern_details_ready(browser, job_id))
            title, company = live['title'], live['company']
            work_location, work_style = live['location'], live['workplace_type']
            skip = company in blacklisted_companies or job_id in rejected_jobs
        buffer(click_gap)
        return job_id, title, company, work_location, work_style, skip
    job_details_button = job.find_element(By.TAG_NAME, 'a')  # job.find_element(By.CLASS_NAME, "job-card-list__title")  # Problem in India
    scroll_to_view(driver, job_details_button, True)
    job_id = job.get_dom_attribute('data-occludable-job-id')
    title = job_details_button.text
    title = title.splitlines()[0]
    # company = job.find_element(By.CLASS_NAME, "job-card-container__primary-description").text
    # work_location = job.find_element(By.CLASS_NAME, "job-card-container__metadata-item").text
    other_details = job.find_element(By.CLASS_NAME, 'artdeco-entity-lockup__subtitle').text
    company, separator, work_location = other_details.partition(' · ')
    if not separator:
        lines = [line.strip() for line in other_details.splitlines() if line.strip()]
        company = lines[0] if lines else ""
        work_location = " ".join(lines[1:])
    if not work_location:
        for class_name in ("artdeco-entity-lockup__caption", "job-card-container__metadata-item", "job-card-container__metadata-wrapper"):
            try:
                work_location = job.find_element(By.CLASS_NAME, class_name).text.strip()
                if work_location:
                    break
            except NoSuchElementException:
                continue
    style = re.search(r'\((Remote|Hybrid|On-site)\)', work_location, re.I)
    work_style = style.group(1) if style else "Unknown"
    work_location = re.sub(r'\((Remote|Hybrid|On-site)\)', '', work_location, flags=re.I).strip()
    
    # Skip if previously rejected due to blacklist or already applied
    skip = False
    if company in blacklisted_companies:
        print_lg(f'Skipping "{title} | {company}" job (Blacklisted Company). Job ID: {job_id}!')
        skip = True
    elif job_id in rejected_jobs: 
        print_lg(f'Skipping previously rejected "{title} | {company}" job. Job ID: {job_id}!')
        skip = True
    try:
        if job.find_element(By.CLASS_NAME, "job-card-container__footer-job-state").text == "Applied":
            skip = True
            print_lg(f'Already applied to "{title} | {company}" job. Job ID: {job_id}!')
    except: pass
    try: 
        if not skip: job_details_button.click()
    except Exception as e:
        print_lg(f'Failed to click "{title} | {company}" job on details button. Job ID: {job_id}!') 
        # print_lg(e)
        if not read_only:
            discard_job()
        job_details_button.click() # To pass the error outside
    buffer(click_gap)
    return (job_id,title,company,work_location,work_style,skip)


# Function to check for Blacklisted words in About Company
def check_blacklist(rejected_jobs: set, job_id: str, company: str, blacklisted_companies: set) -> tuple[set, set, WebElement] | ValueError:
    from modules.linkedin_job_details import modern_details_root, read_modern_company
    if modern_details_root(driver, job_id) is not None:
        about_company_org, jobs_top_card = read_modern_company(driver, job_id)
    else:
        jobs_top_card = try_find_by_classes(driver, ["job-details-jobs-unified-top-card__primary-description-container","job-details-jobs-unified-top-card__primary-description","jobs-unified-top-card__primary-description","jobs-details__main-content"])
        about_company_org = find_by_class(driver, "jobs-company__box")
        scroll_to_view(driver, about_company_org)
        about_company_org = about_company_org.text
    about_company = about_company_org.lower()
    skip_checking = False
    for word in about_company_good_words:
        if word.lower() in about_company:
            print_lg(f'Found the word "{word}". So, skipped checking for blacklist words.')
            skip_checking = True
            break
    if not skip_checking:
        for word in about_company_bad_words: 
            if word.lower() in about_company: 
                rejected_jobs.add(job_id)
                blacklisted_companies.add(company)
                raise ValueError(f'\n"{about_company_org}"\n\nContains "{word}".')
    buffer(click_gap)
    scroll_to_view(driver, jobs_top_card)
    return rejected_jobs, blacklisted_companies, jobs_top_card



# Function to extract years of experience required from About Job
def extract_years_of_experience(text: str) -> int:
    # Extract all patterns like '10+ years', '5 years', '3-5 years', etc.
    matches = re.findall(re_experience, text)
    if len(matches) == 0: 
        print_lg(f'\n{text}\n\nCouldn\'t find experience requirement in About the Job!')
        return 0
    return max([int(match) for match in matches if int(match) <= 12])



def get_job_description(
) -> tuple[
    str | Literal['Unknown'],
    int | Literal['Unknown'],
    bool,
    str | None,
    str | None
    ]:
    '''
    # Job Description
    Function to extract job description from About the Job.
    ### Returns:
    - `jobDescription: str | 'Unknown'`
    - `experience_required: int | 'Unknown'`
    - `skip: bool`
    - `skipReason: str | None`
    - `skipMessage: str | None`
    '''
    modern = False
    jobDescription = "Unknown"
    experience_required = "Unknown"
    skip = False
    skipReason = skipMessage = None
    try:
        ##> ------ Dheeraj Deshwal : dheeraj9811 Email:dheeraj20194@iiitd.ac.in/dheerajdeshwal9811@gmail.com - Feature ------
        jobDescription = "Unknown"
        ##<
        experience_required = "Unknown"
        found_masters = 0
        from modules.linkedin_job_details import read_modern_description
        modern = bool(driver.find_elements("css selector", "[data-view-name='job-detail-page'], [id^='JobDetails_AboutTheJob_']"))
        jobDescription = read_modern_description(driver) if modern else find_by_class(driver, "jobs-box__html-content").text
        jobDescriptionLow = jobDescription.lower()
        skip = False
        skipReason = None
        skipMessage = None
        for word in bad_words:
            if word.lower() in jobDescriptionLow:
                skipMessage = f'\n{jobDescription}\n\nContains bad word "{word}". Skipping this job!\n'
                skipReason = "Found a Bad Word in About Job"
                skip = True
                break
        if not skip and security_clearance == False and ('polygraph' in jobDescriptionLow or 'clearance' in jobDescriptionLow or 'secret' in jobDescriptionLow):
            skipMessage = f'\n{jobDescription}\n\nFound "Clearance" or "Polygraph". Skipping this job!\n'
            skipReason = "Asking for Security clearance"
            skip = True
        if not skip:
            if did_masters and 'master' in jobDescriptionLow:
                print_lg(f'Found the word "master" in \n{jobDescription}')
                found_masters = 2
            experience_required = extract_years_of_experience(jobDescription)
            if current_experience > -1 and experience_required > current_experience + found_masters:
                skipMessage = f'\n{jobDescription}\n\nExperience required {experience_required} > Current Experience {current_experience + found_masters}. Skipping this job!\n'
                skipReason = "Required experience is high"
                skip = True
    except Exception as e:
        if modern:
            skip, skipReason, skipMessage = True, "Full modern job description unavailable", str(e)
        elif jobDescription == "Unknown":    print_lg("Unable to extract job description!")
        else:
            experience_required = "Error in extraction"
            print_lg("Unable to extract years of experience required!")
            # print_lg(e)
    return jobDescription, experience_required, skip, skipReason, skipMessage
        


# Function to upload resume
def upload_resume(modal: WebElement, resume: str) -> tuple[bool, str]:
    try:
        modal.find_element(By.NAME, "file").send_keys(os.path.abspath(resume))
        return True, os.path.basename(default_resume_path)
    except: return False, "Previous resume"

# Function to upload optimized resume using run_resume_optimization function from resume_optimizer.py similar logic to upload_resume function
def upload_optimized_resume(modal: WebElement, resume_path: str, job_description: str, job_id: str, job_title: str = "job", first_name: str = "first", last_name: str = "last") -> tuple[bool, str]:
    return upload_verified_resume(
        modal, resume_path, job_description, job_id, job_title, first_name, last_name,
        optimize=run_resume_optimization, log=print_lg,
    )

# Function to answer common questions for Easy Apply
def answer_common_questions(label: str, answer: str) -> str:
    if 'sponsorship' in label or 'visa' in label: answer = require_visa
    return answer


# Function to answer the questions for Easy Apply
def answer_questions(modal: WebElement, questions_list: set, work_location: str, job_description: str | None = None ) -> set:
    # Get all questions from the page
     
    all_questions = modal.find_elements(By.XPATH, ".//div[@data-test-form-element]")
    # all_questions = modal.find_elements(By.CLASS_NAME, "jobs-easy-apply-form-element")
    # all_list_questions = modal.find_elements(By.XPATH, ".//div[@data-test-text-entity-list-form-component]")
    # all_single_line_questions = modal.find_elements(By.XPATH, ".//div[@data-test-single-line-text-form-component]")
    # all_questions = all_questions + all_list_questions + all_single_line_questions

    for Question in all_questions:
        # Check if it's a select Question
        select = try_xp(Question, ".//select", False)
        if select:
            label_org = "Unknown"
            try:
                label = Question.find_element(By.TAG_NAME, "label")
                label_org = label.find_element(By.TAG_NAME, "span").text
            except: pass
            answer = 'Yes'
            label = label_org.lower()
            select = Select(select)
            selected_option = select.first_selected_option.text
            optionsText = []
            options = '"List of phone country codes"'
            if label != "phone country code":
                optionsText = [option.text for option in select.options]
                options = "".join([f' "{option}",' for option in optionsText])
            prev_answer = selected_option
            if overwrite_previous_answers or selected_option == "Select an option":
                if 'email' in label or 'phone' in label: answer = prev_answer
                elif 'gender' in label or 'sex' in label: answer = gender
                elif 'disability' in label: answer = disability_status
                elif 'proficiency' in label: answer = 'Professional'
                else: answer = answer_common_questions(label,answer)
                try: select.select_by_visible_text(answer)
                except NoSuchElementException as e:
                    possible_answer_phrases = ["Decline", "not wish", "don't wish", "Prefer not", "not want"] if answer == 'Decline' else [answer]
                    foundOption = False
                    for phrase in possible_answer_phrases:
                        for option in optionsText:
                            if phrase in option:
                                select.select_by_visible_text(option)
                                answer = f'Decline ({option})' if len(possible_answer_phrases) > 1 else option
                                foundOption = True
                                break
                        if foundOption: break
                    if not foundOption:
                        #TODO: Use AI to answer the question need to be implemented logic to extract the options for the question
                        print_lg(f'Failed to find an option with text "{answer}" for question labelled "{label_org}", answering randomly!')
                        select.select_by_index(randint(1, len(select.options)-1))
                        answer = select.first_selected_option.text
                        randomly_answered_questions.add((f'{label_org} [ {options} ]',"select"))
            questions_list.add((f'{label_org} [ {options} ]', answer, "select", prev_answer))
            continue
        
        # Check if it's a radio Question
        radio = try_xp(Question, './/fieldset[@data-test-form-builder-radio-button-form-component="true"]', False)
        if radio:
            prev_answer = None
            label = try_xp(radio, './/span[@data-test-form-builder-radio-button-form-component__title]', False)
            try: label = find_by_class(label, "visually-hidden", 2.0)
            except: pass
            label_org = label.text if label else "Unknown"
            answer = 'Yes'
            label = label_org.lower()

            label_org += ' [ '
            options = radio.find_elements(By.TAG_NAME, 'input')
            options_labels = []
            
            for option in options:
                id = option.get_attribute("id")
                option_label = try_xp(radio, f'.//label[@for="{id}"]', False)
                options_labels.append( f'"{option_label.text if option_label else "Unknown"}"<{option.get_attribute("value")}>' ) # Saving option as "label <value>"
                if option.is_selected(): prev_answer = options_labels[-1]
                label_org += f' {options_labels[-1]},'

            if overwrite_previous_answers or prev_answer is None:
                if 'citizenship' in label or 'employment eligibility' in label: answer = us_citizenship
                elif 'veteran' in label or 'protected' in label: answer = veteran_status
                elif 'disability' in label or 'handicapped' in label: 
                    answer = disability_status
                else: answer = answer_common_questions(label,answer)
                foundOption = try_xp(radio, f".//label[normalize-space()='{answer}']", False)
                if foundOption: 
                    actions.move_to_element(foundOption).click().perform()
                else:    
                    possible_answer_phrases = ["Decline", "not wish", "don't wish", "Prefer not", "not want"] if answer == 'Decline' else [answer]
                    ele = options[0]
                    answer = options_labels[0]
                    for phrase in possible_answer_phrases:
                        for i, option_label in enumerate(options_labels):
                            if phrase in option_label:
                                foundOption = options[i]
                                ele = foundOption
                                answer = f'Decline ({option_label})' if len(possible_answer_phrases) > 1 else option_label
                                break
                        if foundOption: break
                    # if answer == 'Decline':
                    #     answer = options_labels[0]
                    #     for phrase in ["Prefer not", "not want", "not wish"]:
                    #         foundOption = try_xp(radio, f".//label[normalize-space()='{phrase}']", False)
                    #         if foundOption:
                    #             answer = f'Decline ({phrase})'
                    #             ele = foundOption
                    #             break
                    actions.move_to_element(ele).click().perform()
                    if not foundOption: randomly_answered_questions.add((f'{label_org} ]',"radio"))
            else: answer = prev_answer
            questions_list.add((label_org+" ]", answer, "radio", prev_answer))
            continue
        
        # Check if it's a text question
        text = try_xp(Question, ".//input[@type='text']", False)
        if text: 
            do_actions = False
            label = try_xp(Question, ".//label[@for]", False)
            try: label = label.find_element(By.CLASS_NAME,'visually-hidden')
            except: pass
            label_org = label.text if label else "Unknown"
            answer = "" # years_of_experience
            label = label_org.lower()

            prev_answer = text.get_attribute("value")
            if not prev_answer or overwrite_previous_answers:
                if 'experience' in label or 'years' in label: answer = years_of_experience
                elif 'phone' in label or 'mobile' in label: answer = phone_number
                elif 'street' in label: answer = street
                elif 'city' in label or 'location' in label or 'address' in label:
                    answer = current_city if current_city else work_location
                    do_actions = True
                elif 'signature' in label: answer = full_name # 'signature' in label or 'legal name' in label or 'your name' in label or 'full name' in label: answer = full_name     # What if question is 'name of the city or university you attend, name of referral etc?'
                elif 'name' in label:
                    if 'full' in label: answer = full_name
                    elif 'first' in label and 'last' not in label: answer = first_name
                    elif 'middle' in label and 'last' not in label: answer = middle_name
                    elif 'last' in label and 'first' not in label: answer = last_name
                    elif 'employer' in label: answer = recent_employer
                    else: answer = full_name
                elif 'notice' in label:
                    if 'month' in label:
                        answer = notice_period_months
                    elif 'week' in label:
                        answer = notice_period_weeks
                    else: answer = notice_period
                elif 'salary' in label or 'compensation' in label or 'ctc' in label or 'pay' in label: 
                    if 'current' in label or 'present' in label:
                        if 'month' in label:
                            answer = current_ctc_monthly
                        elif 'lakh' in label:
                            answer = current_ctc_lakhs
                        else:
                            answer = current_ctc
                    else:
                        if 'month' in label:
                            answer = desired_salary_monthly
                        elif 'lakh' in label:
                            answer = desired_salary_lakhs
                        else:
                            answer = desired_salary
                elif 'linkedin' in label: answer = linkedIn
                elif 'website' in label or 'blog' in label or 'portfolio' in label or 'link' in label: answer = website
                elif 'scale of 1-10' in label: answer = confidence_level
                elif 'headline' in label: answer = linkedin_headline
                elif ('hear' in label or 'come across' in label) and 'this' in label and ('job' in label or 'position' in label): answer = "https://github.com/dannyb66/jobrobo"
                elif 'state' in label or 'province' in label: answer = state
                elif 'zip' in label or 'postal' in label or 'code' in label: answer = zipcode
                elif 'country' in label: answer = country
                else: answer = answer_common_questions(label,answer)
                ##> ------ Dheeraj Deshwal : dheeraj9811 Email:dheeraj20194@iiitd.ac.in/dheerajdeshwal9811@gmail.com - Feature ------
                if answer == "":
                    if use_AI and aiClient:
                        try:
                             answer = ai_answer_question(aiClient, label_org, question_type="text" ,job_description=job_description, user_information_all = user_information_all)
                             print_lg(f'AI Answered recived for question"{label_org}" \nhere is answer : "{answer}"')
                        except Exception as e:
                            print_lg("Failed to get AI answer!", e)
                    else:
                        randomly_answered_questions.add((label_org, "text"))
                        answer = years_of_experience
                 ##<   
                text.clear()
                text.send_keys(answer)
                if do_actions:
                    sleep(2)
                    actions.send_keys(Keys.ARROW_DOWN)
                    actions.send_keys(Keys.ENTER).perform()
            questions_list.add((label, text.get_attribute("value"), "text", prev_answer))
            continue

        # Check if it's a textarea question
        text_area = try_xp(Question, ".//textarea", False)
        if text_area:
            label = try_xp(Question, ".//label[@for]", False)
            label_org = label.text if label else "Unknown"
            label = label_org.lower()
            answer = ""
            prev_answer = text_area.get_attribute("value")
            if not prev_answer or overwrite_previous_answers:
                if 'summary' in label: answer = linkedin_summary
                elif 'cover' in label: answer = cover_letter
                if answer == "":
                ##> ------ Dheeraj Deshwal : dheeraj9811 Email:dheeraj20194@iiitd.ac.in/dheerajdeshwal9811@gmail.com - Feature ------
                    if use_AI and aiClient:
                        try:
                             answer = ai_answer_question(aiClient, label_org, question_type="textarea" ,job_description=job_description, user_information_all = user_information_all)
                             print_lg(f'AI Answered recived for question"{label_org}" \nhere is answer : "{answer}"')
                        except Exception as e:
                            print_lg("Failed to get AI answer!", e)
                    else:
                        randomly_answered_questions.add((label_org, "textarea"))
            text_area.clear()
            text_area.send_keys(answer)
            if do_actions:
                    sleep(2)
                    actions.send_keys(Keys.ARROW_DOWN)
                    actions.send_keys(Keys.ENTER).perform()
            questions_list.add((label, text_area.get_attribute("value"), "textarea", prev_answer))
            ##<
            continue

        # Check if it's a checkbox question
        checkbox = try_xp(Question, ".//input[@type='checkbox']", False)
        if checkbox:
            label = try_xp(Question, ".//span[@class='visually-hidden']", False)
            label_org = label.text if label else "Unknown"
            label = label_org.lower()
            answer = try_xp(Question, ".//label[@for]", False)  # Sometimes multiple checkboxes are given for 1 question, Not accounted for that yet
            answer = answer.text if answer else "Unknown"
            prev_answer = checkbox.is_selected()
            checked = prev_answer
            if not prev_answer:
                try:
                    actions.move_to_element(checkbox).click().perform()
                    checked = True
                except Exception as e: 
                    print_lg("Checkbox click failed!", e)
                    pass
            questions_list.add((f'{label} ([X] {answer})', checked, "checkbox", prev_answer))
            continue


    # Select todays date
    try_xp(driver, "//button[contains(@aria-label, 'This is today')]")

    # Collect important skills
    # if 'do you have' in label and 'experience' in label and ' in ' in label -> Get word (skill) after ' in ' from label
    # if 'how many years of experience do you have in ' in label -> Get word (skill) after ' in '

    return questions_list




def external_apply(pagination_element: WebElement, job_id: str, job_link: str, resume: str, date_listed, application_link: str, screenshot_name: str) -> tuple[bool, str, int]:
    '''
    Function to open new tab and save external job application links
    '''
    global tabs_count, dailyEasyApplyLimitReached
    if easy_apply_only:
        try:
            if "exceeded the daily application limit" in driver.find_element(By.CLASS_NAME, "artdeco-inline-feedback__message").text: dailyEasyApplyLimitReached = True
        except: pass
        print_lg("Easy apply failed I guess!")
        if pagination_element != None: return True, application_link, tabs_count
    try:
        wait.until(EC.element_to_be_clickable((By.XPATH, ".//button[contains(@class,'jobs-apply-button') and contains(@class, 'artdeco-button--3')]"))).click() # './/button[contains(span, "Apply") and not(span[contains(@class, "disabled")])]'
        wait_span_click(driver, "Continue", 1, True, False)
        windows = driver.window_handles
        tabs_count = len(windows)
        driver.switch_to.window(windows[-1])
        application_link = driver.current_url
        print_lg('Got the external application link "{}"'.format(application_link))
        if close_tabs and driver.current_window_handle != linkedIn_tab: driver.close()
        driver.switch_to.window(linkedIn_tab)
        return False, application_link, tabs_count
    except Exception as e:
        # print_lg(e)
        print_lg("Failed to apply!")
        failed_job(job_id, job_link, resume, date_listed, "Probably didn't find Apply button or unable to switch tabs.", e, application_link, screenshot_name)
        global failed_count
        failed_count += 1
        return True, application_link, tabs_count



def follow_company(modal: WebDriver = None) -> None:
    '''
    Function to follow or un-follow easy applied companies based om `follow_companies`
    '''
    modal = driver if modal is None else modal
    try:
        follow_checkbox_input = try_xp(modal, ".//input[@id='follow-company-checkbox' and @type='checkbox']", False)
        if follow_checkbox_input and follow_checkbox_input.is_selected() != follow_companies:
            try_xp(modal, ".//label[@for='follow-company-checkbox']")
    except Exception as e:
        print_lg("Failed to update follow companies checkbox!", e)
    


#< Failed attempts logging
def failed_job(job_id: str, job_link: str, resume: str, date_listed, error: str, exception: Exception, application_link: str, screenshot_name: str) -> None:
    '''
    Function to update failed jobs list in excel
    '''
    try:
        fieldnames = ['Job ID', 'Job Link', 'Resume Tried', 'Date listed', 'Date Tried', 'Assumed Reason', 'Stack Trace', 'External Job link', 'Screenshot Name']
        row = {'Job ID':job_id, 'Job Link':job_link, 'Resume Tried':resume, 'Date listed':date_listed, 'Date Tried':datetime.now(), 'Assumed Reason':error, 'Stack Trace':exception, 'External Job link':application_link, 'Screenshot Name':screenshot_name}
        row.update(search_metadata(active_manifest, active_search))
        checkpoint_job(job_id, "skipped" if application_link == "Skipped" else "failed", str(error))
        append_history(failed_file_name, fieldnames, row)
    except Exception as e:
        print_lg("Failed to update failed jobs list!", e)
        pyautogui.alert("Failed to update the excel of failed jobs!\nProbably because of 1 of the following reasons:\n1. The file is currently open or in use by another program\n2. Permission denied to write to the file\n3. Failed to find the file", "Failed Logging")


def screenshot(driver: WebDriver, job_id: str, failedAt: str) -> str:
    '''
    Function to to take screenshot for debugging
    - Returns screenshot name as String
    '''
    screenshot_name = "{} - {} - {}.png".format( job_id, failedAt, str(datetime.now()) )
    path = logs_folder_path+"/screenshots/"+screenshot_name.replace(":",".")
    # special_chars = {'*', '"', '\\', '<', '>', ':', '|', '?'}
    # for char in special_chars:  path = path.replace(char, '-')
    driver.save_screenshot(path.replace("//","/"))
    return screenshot_name
#>



def submitted_jobs(job_id: str, title: str, company: str, work_location: str, work_style: str, description: str, experience_required: int | Literal['Unknown', 'Error in extraction'], 
                   skills: list[str] | Literal['In Development'], hr_name: str | Literal['Unknown'], hr_link: str | Literal['Unknown'], resume: str, 
                   reposted: bool, date_listed: datetime | Literal['Unknown'], date_applied:  datetime | Literal['Pending'], job_link: str, application_link: str, 
                   questions_list: set | None, connect_request: Literal['In Development']) -> None:
    '''
    Function to create or update the Applied jobs CSV file, once the application is submitted successfully
    '''
    try:
        fieldnames = ['Job ID', 'Title', 'Company', 'Work Location', 'Work Style', 'About Job', 'Experience required', 'Skills required', 'HR Name', 'HR Link', 'Resume', 'Re-posted', 'Date Posted', 'Date Applied', 'Job Link', 'External Job link', 'Questions Found', 'Connect Request']
        row = {'Job ID':job_id, 'Title':title, 'Company':company, 'Work Location':work_location, 'Work Style':work_style,
               'About Job':description, 'Experience required':experience_required, 'Skills required':skills,
               'HR Name':hr_name, 'HR Link':hr_link, 'Resume':resume, 'Re-posted':reposted,
               'Date Posted':date_listed, 'Date Applied':date_applied, 'Job Link':job_link,
               'External Job link':application_link, 'Questions Found':questions_list, 'Connect Request':connect_request}
        row.update(search_metadata(active_manifest, active_search))
        append_history(file_name, fieldnames, row)
    except Exception as e:
        print_lg("Failed to update submitted jobs list!", e)
        pyautogui.alert("Failed to update the excel of applied jobs!\nProbably because of 1 of the following reasons:\n1. The file is currently open or in use by another program\n2. Permission denied to write to the file\n3. Failed to find the file", "Failed Logging")



# Function to discard the job application
def discard_job() -> None:
    actions.send_keys(Keys.ESCAPE).perform()
    wait_span_click(driver, 'Discard', 2)






def selected_live_details(record, spec):
    """Re-read the selected LinkedIn posting before opening any application form."""
    from modules.job_pipeline.linkedin import company_matches
    from datetime import timezone
    from urllib.parse import urlparse, parse_qs
    job_id = str(record["linkedin_id"])
    url = urlparse(driver.current_url)
    path_id = re.search(r"/jobs/view/(?:[^/]*-)?([0-9]+)/?", url.path)
    live_id = path_id.group(1) if path_id else (parse_qs(url.query).get("currentJobId") or [None])[0]
    if url.hostname not in {"www.linkedin.com", "linkedin.com"} or live_id != job_id:
        raise ValueError("Selected LinkedIn ID could not be verified after navigation")
    if driver.find_elements(By.CSS_SELECTOR, "[data-view-name='job-detail-page'], [id^='JobDetails_AboutTheJob_']"):
        from modules.linkedin_job_details import modern_details_ready
        live = WebDriverWait(driver, 15).until(lambda browser: modern_details_ready(browser, job_id))
        company = live["company"]
        posted = calculate_date_posted(live["posted_text"]) if live["posted_text"] else None
        record["_live_details"] = {
            "workplace_type": live["workplace_type"], "employment_type": live["employment_type"],
            "locations": [live["location"]],
            "published_at": posted.astimezone(timezone.utc).isoformat() if posted else None,
        }
        allowed = spec.filters_snapshot["intent"].get("on_site") or []
        skip = (not company_matches(spec.pipeline_context["company"], company, live["company_url"])
                or bool(allowed and live["workplace_type"] not in allowed))
        return job_id, live["title"], company, live["location"], live["workplace_type"], skip
    title_node = WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.TAG_NAME, "h1")))
    anchors = driver.find_elements(By.CSS_SELECTOR, ".job-details-jobs-unified-top-card__company-name a, .jobs-unified-top-card__company-name a")
    if not anchors:
        raise ValueError("Live employer identity unavailable; selected job was not applied")
    company = anchors[0].text.strip()
    company_url = anchors[0].get_attribute("href")
    if not company_matches(spec.pipeline_context["company"], company, company_url):
        return job_id, title_node.text, company, "Unknown", "Unknown", True
    metadata = driver.find_elements(By.CSS_SELECTOR, ".job-details-jobs-unified-top-card__primary-description-container, .jobs-unified-top-card__primary-description")
    text = " ".join(node.text for node in metadata)
    styles = driver.find_elements(By.CSS_SELECTOR, ".job-details-jobs-unified-top-card__job-insight, .jobs-unified-top-card__job-insight")
    style_text = " ".join(node.text for node in styles) + " " + text
    style = next((value for value in ("Remote", "Hybrid", "On-site") if re.search(r"\b" + value + r"\b", style_text, re.I)), "Unknown")
    employment = next((value for value in ("Full-time", "Part-time", "Contract", "Temporary", "Internship") if value.casefold() in style_text.casefold()), "Unknown")
    date_nodes = driver.find_elements(By.CSS_SELECTOR, ".job-details-jobs-unified-top-card__tertiary-description-container, .jobs-unified-top-card__posted-date")
    date_text = " ".join(node.text for node in date_nodes)
    posted_match = re.search(r"(?:\d+\s+(?:minute|hour|day|week|month)s? ago|today|just now)", date_text, re.I)
    posted = calculate_date_posted(posted_match.group()) if posted_match else None
    record["_live_details"] = {"workplace_type": style, "employment_type": employment,
                               "locations": [text], "published_at": posted.astimezone(timezone.utc).isoformat() if posted else None}
    allowed = spec.filters_snapshot["intent"].get("on_site") or []
    skip = bool(allowed and style not in allowed)
    return job_id, title_node.text.strip(), company, text or "Unknown", style, skip


def application_outcome(manifest, spec, job_id):
    from copy import deepcopy
    row = manifest.query(spec.query_id)
    context = deepcopy(spec.pipeline_context)
    return dict(
        id="linkedin:" + str(job_id), job_id=str(job_id), linkedin_id=str(job_id),
        job_link="https://www.linkedin.com/jobs/view/" + str(job_id),
        **row["jobs"][str(job_id)], company=context.get("company"),
        company_id=context.get("company_id"), career_job_ids=context.get("career_job_ids", []),
        career_roles=context.get("career_roles", []), verification_run_ids=context.get("verification_run_ids", []),
        query_id=spec.query_id, query_text=spec.query_text, classic_query=spec.classic_query,
        search_mode=row.get("search_mode") or spec.mode, search_source=spec.source,
        search_run_id=manifest.data["run_id"], search_spec=spec.to_dict(),
        fallback_reason=row.get("fallback_reason"), warnings=list(row.get("warnings", [])),
        search_diagnostics=deepcopy(row.get("search_diagnostics", {})),
        profile_name=spec.profile_name, profile_version=spec.profile_version,
    )


def collect_linkedin_jobs(specs, *, limit=25, result_sink=None, checkpoints=None, checkpoint_sink=None, refresh=False):
    """Read job details and persist matches; never open forms or upload a resume."""
    from copy import deepcopy
    from modules.job_pipeline.models import utc_now
    from modules.job_pipeline.linkedin import company_matches, role_matches
    records, errors, seen = [], [], set()
    for spec in specs:
        if len(records) >= limit:
            break
        checkpoint = (checkpoints or {}).get(spec.query_id) or {}
        fingerprint = plan_fingerprint([spec])
        if not refresh and checkpoint.get("complete") and checkpoint.get("fingerprint") == fingerprint:
            continue
        processed = set(checkpoint.get("processed_ids", [])) if not refresh and checkpoint.get("fingerprint") == fingerprint else set()
        accepted, page = 0, 1
        try:
            result = prepare_search(driver, spec, wait_for_search, wait_for_search_results, apply_filters)
            spec.mode = result.mode
            warnings = list(result.warnings)
            while len(records) < limit:
                listings = get_search_cards(driver)
                if not listings:
                    if search_results_ready(driver) != "empty":
                        raise ValueError("LinkedIn result cards unavailable; scan is incomplete")
                    break
                pagination, page = get_page_info()
                for card in listings:
                    job_id = str(search_card_id(card) or "")
                    if not job_id.isdigit() or job_id in seen or job_id in processed:
                        continue
                    job_id, title, company, location, style, skip_card = get_job_main_details(card, set(), set(), read_only=True)
                    if skip_card:
                        processed.add(job_id)
                        continue
                    try:
                        check_blacklist(set(), job_id, company, set())
                        description, _, skip, _, _ = get_job_description()
                        allowed = spec.filters_snapshot["intent"].get("on_site") or []
                        eligible = (not skip and description != "Unknown" and company_matches(spec.pipeline_context["company"], company)
                                    and role_matches(title, description, spec) and (not allowed or style in allowed))
                    except ValueError:
                        eligible = False
                    if eligible:
                        context = deepcopy(spec.pipeline_context)
                        record = dict(
                            id="linkedin:" + job_id, job_id=job_id, linkedin_id=job_id,
                            job_link="https://www.linkedin.com/jobs/view/" + job_id, url="https://www.linkedin.com/jobs/view/" + job_id,
                            title=title, description=description, location=location, workplace_type=style,
                            eligible=True, status="open", company=context["company"], company_id=context["company_id"],
                            career_job_ids=context["career_job_ids"], career_roles=context["career_roles"],
                            verification_run_ids=context["verification_run_ids"], priority_tier=context["priority_tier"],
                            query_id=spec.query_id, query_text=spec.query_text, classic_query=spec.classic_query,
                            search_mode=result.mode, search_source=spec.source, search_spec=spec.to_dict(),
                            profile_name=spec.profile_name, profile_version=spec.profile_version,
                            fallback_reason=result.fallback_reason, warnings=warnings,
                            search_diagnostics=result.diagnostics(),
                            discovered_at=utc_now(), match_relationship="company_engineering_family",
                            eligibility_basis="company_identity_role_family_and_description",
                            unverified_preferences=["employment_type", "posted_date", "live_location"],
                        )
                        records.append(record)
                        if result_sink:
                            result_sink(record)
                        seen.add(job_id)
                        accepted += 1
                    processed.add(job_id)
                    if checkpoint_sink:
                        checkpoint_sink(spec.query_id, {"fingerprint": fingerprint, "processed_ids": sorted(processed), "last_page": page or 1, "complete": False})
                    if len(records) >= limit:
                        break
                if len(records) >= limit or pagination is None:
                    break
                if not next_search_page(driver, page or 1):
                    break
                wait_for_search_results(listings)
            if checkpoint_sink:
                checkpoint_sink(spec.query_id, {"fingerprint": fingerprint, "processed_ids": sorted(processed), "last_page": page or 1, "complete": len(records) < limit, "stop_reason": "results_exhausted" if len(records) < limit else "scan_limit"})
        except Exception as error:
            error_record = {"query_id": spec.query_id, "code": type(error).__name__, "message": str(error), "retryable": True}
            diagnostics = getattr(error, "diagnostics", None)
            if diagnostics is not None:
                error_record["search_diagnostics"] = diagnostics() if callable(diagnostics) else diagnostics
            errors.append(error_record)
    return records, errors


# Function to apply to jobs
def execute_search_plan(manifest, *, selected_jobs=None, result_sink=None, job_limit=None, application_budget=None) -> None:
    applied_jobs = get_applied_job_ids()
    rejected_jobs = set()
    blacklisted_companies = set()
    processed_this_run = 0
    global active_search, active_page, current_city, failed_count, skip_count, easy_applied_count, external_jobs_count, tabs_count, pause_before_submit, pause_at_failed_question, useNewResume, active_application_budget
    active_application_budget = application_budget
    current_city = current_city.strip()

    for spec in manifest.queries():
        if application_budget is not None and application_budget.stop_if_reached(manifest):
            return
        if spec.pipeline_context and globals().get("current_pipeline_run_id"):
            spec.pipeline_context["pipeline_run_id"] = current_pipeline_run_id
            manifest.query(spec.query_id)["spec"]["pipeline_context"] = spec.pipeline_context
        active_search = spec
        active_page = 1
        active_job_id = None
        manifest.begin_query(spec)
        if manifest.has_uncertain_submission(spec):
            row = manifest.query(spec.query_id)
            row["status"], row["stop_reason"] = "pending", "submission_uncertain"
            manifest.save()
            print_lg(f"Query {spec.query_id} awaits verification of an uncertain submission on LinkedIn")
            continue
        if manifest.quota_met(spec):
            manifest.finish_query(spec, "quota_met")
            continue
        try:
            if selected_jobs is None:
                result = prepare_search(driver, spec, wait_for_search, wait_for_search_results, apply_filters)
            else:
                from modules.linkedin_search import SearchResult
                result = SearchResult(spec.mode)
            manifest.record_mode(spec, result.mode, result.fallback_reason, result.warnings,
                                 diagnostics=result.diagnostics())
            print_lg(f'Now searching [{spec.query_id}, {spec.mode}]: {spec.query_text}')
            warnings = list(result.warnings)
            for warning in warnings:
                print_lg(warning)
            while not manifest.quota_met(spec) and not manifest.has_uncertain_submission(spec):
                if selected_jobs is None:
                    wait_for_search_results([])
                    pagination_element, current_page = get_page_info()
                    active_page = current_page or 1
                    buffer(3)
                    job_listings = get_search_cards(driver)
                    if not job_listings and search_results_ready(driver) != "empty":
                        raise ValueError("LinkedIn result cards unavailable; scan is incomplete")
                else:
                    pagination_element, current_page, active_page = None, 1, 1
                    job_listings = list(selected_jobs.get(spec.query_id, []))

                for job in job_listings:
                    if application_budget is not None and application_budget.stop_if_reached(manifest, spec):
                        return
                    if keep_screen_awake: pyautogui.press('shiftright')
                    if manifest.quota_met(spec) or manifest.has_uncertain_submission(spec): break
                    raw_job_id = str(job.get('linkedin_id', '')) if isinstance(job, dict) else search_card_id(job)
                    if not raw_job_id:
                        continue
                    if raw_job_id in manifest.processed_ids():
                        continue
                    if raw_job_id in applied_jobs:
                        checkpoint_job(raw_job_id, "skipped", "Previously applied or awaiting submission verification in durable history")
                        continue
                    if job_limit is not None and processed_this_run >= job_limit:
                        manifest.interrupt("work_limit")
                        return
                    processed_this_run += 1
                    active_job_id = raw_job_id
                    checkpoint_job(raw_job_id, "in_progress", "Job processing started")
                    print_lg("\n-@-\n")

                    if isinstance(job, dict):
                        driver.get("https://www.linkedin.com/jobs/view/" + raw_job_id)
                        job_id,title,company,work_location,work_style,skip = selected_live_details(job, spec)
                    else:
                        job_id,title,company,work_location,work_style,skip = get_job_main_details(job, blacklisted_companies, rejected_jobs)
                    from modules.job_pipeline.careers import location_reasons
                    geography_rejections = location_reasons(
                        [work_location], work_style, spec.filters_snapshot["intent"].get("search_location", ""),
                    )
                    if geography_rejections:
                        failed_job(job_id, "https://www.linkedin.com/jobs/view/" + job_id, "Pending", "Unknown",
                                   "Location rejected: " + ", ".join(geography_rejections),
                                   f"Observed {work_location!r} ({work_style}); configured location: {spec.filters_snapshot['intent'].get('search_location')}",
                                   "Skipped", "Not Available")
                        skip_count += 1
                        continue
                    if spec.pipeline_context:
                        from modules.job_pipeline.linkedin import company_matches
                        if not company_matches(spec.pipeline_context["company"], company):
                            checkpoint_job(job_id, "skipped", "Employer does not match verified company")
                            continue
                    
                    if skip:
                        failed_job(job_id, "https://www.linkedin.com/jobs/view/" + job_id, "Pending", "Unknown",
                                   "Previously applied or rejected by company gates", "", "Skipped", "Not Available")
                        continue
                    # Redundant fail safe check for applied jobs!
                    try:
                        if job_id in applied_jobs or find_by_class(driver, "jobs-s-apply__application-link", 2):
                            print_lg(f'Already applied to "{title} | {company}" job. Job ID: {job_id}!')
                            checkpoint_job(job_id, 'skipped', 'Previously applied on LinkedIn')
                            continue
                    except Exception as e:
                        print_lg(f'Trying to Apply to "{title} | {company}" job. Job ID: {job_id}')

                    job_link = "https://www.linkedin.com/jobs/view/"+job_id
                    application_link = "Easy Applied"
                    date_applied = "Pending"
                    hr_link = "Unknown"
                    hr_name = "Unknown"
                    connect_request = "In Development" # Still in development
                    date_listed = "Unknown"
                    skills = "Needs an AI" # Still in development
                    resume = "Pending"
                    reposted = False
                    questions_list = None
                    screenshot_name = "Not Available"

                    try:
                        rejected_jobs, blacklisted_companies, jobs_top_card = check_blacklist(rejected_jobs,job_id,company,blacklisted_companies)
                    except ValueError as e:
                        print_lg(e, 'Skipping this job!\n')
                        failed_job(job_id, job_link, resume, date_listed, "Found Blacklisted words in About Company", e, "Skipped", screenshot_name)
                        skip_count += 1
                        continue
                    except Exception as e:
                        print_lg("Failed to scroll to About Company!")
                        # print_lg(e)



                    # Hiring Manager info
                    try:
                        hr_info_card = WebDriverWait(driver,2).until(EC.presence_of_element_located((By.CLASS_NAME, "hirer-card__hirer-information")))
                        hr_link = hr_info_card.find_element(By.TAG_NAME, "a").get_attribute("href")
                        hr_name = hr_info_card.find_element(By.TAG_NAME, "span").text
                        # if connect_hr:
                        #     driver.switch_to.new_window('tab')
                        #     driver.get(hr_link)
                        #     wait_span_click("More")
                        #     wait_span_click("Connect")
                        #     wait_span_click("Add a note")
                        #     message_box = driver.find_element(By.XPATH, "//textarea")
                        #     message_box.send_keys(connect_request_message)
                        #     if close_tabs: driver.close()
                        #     driver.switch_to.window(linkedIn_tab) 
                        # def message_hr(hr_info_card):
                        #     if not hr_info_card: return False
                        #     hr_info_card.find_element(By.XPATH, ".//span[normalize-space()='Message']").click()
                        #     message_box = driver.find_element(By.XPATH, "//div[@aria-label='Write a message…']")
                        #     message_box.send_keys()
                        #     try_xp(driver, "//button[normalize-space()='Send']")        
                    except Exception as e:
                        print_lg(f'HR info was not given for "{title}" with Job ID: {job_id}!')
                        # print_lg(e)


                    # Calculation of date posted
                    try:
                        # try: time_posted_text = find_by_class(driver, "jobs-unified-top-card__posted-date", 2).text
                        # except: 
                        time_posted_text = jobs_top_card.find_element(By.XPATH, './/span[contains(normalize-space(), " ago")]').text
                        print("Time Posted: " + time_posted_text)
                        if time_posted_text.__contains__("Reposted"):
                            reposted = True
                            time_posted_text = time_posted_text.replace("Reposted", "")
                        date_listed = calculate_date_posted(time_posted_text)
                    except Exception as e:
                        print_lg("Failed to calculate the date posted!",e)


                    description, experience_required, skip, reason, message = get_job_description()
                    if skip:
                        print_lg(message)
                        failed_job(job_id, job_link, resume, date_listed, reason, message, "Skipped", screenshot_name)
                        rejected_jobs.add(job_id)
                        skip_count += 1
                        continue

                    
                    if spec.pipeline_context:
                        from modules.job_pipeline.linkedin import role_matches
                        if isinstance(job, dict) and job.get("_live_details"):
                            from modules.job_pipeline.careers import evaluate_role
                            live_role = dict(job["_live_details"], title=title, description=description,
                                             company=spec.pipeline_context["company"], status="open")
                            canonical = dict(spec.filters_snapshot["intent"], **spec.filters_snapshot["gates"])
                            if not evaluate_role(live_role, canonical)["eligible"]:
                                checkpoint_job(job_id, "skipped", "Live eligibility changed: " + ", ".join(live_role["exclusion_reasons"]))
                                continue
                        if not role_matches(title, description, spec):
                            checkpoint_job(job_id, "skipped", "Role is outside verified engineering family or seniority")
                            continue
                    if use_AI and aiClient and description != "Unknown":
                        skills = ai_extract_skills(aiClient, description)

                    uploaded = False
                    # Case 1: Easy Apply Button
                    if try_xp(driver, ".//button[contains(@class,'jobs-apply-button') and contains(@class, 'artdeco-button--3') and contains(@aria-label, 'Easy')] | //*[@data-view-name='job-detail-page']//button[@aria-label='Easy Apply to this job'] | //*[@id='JobDetails_AboutTheJob_" + job_id + "']/ancestor::*[.//*[starts-with(@aria-label,'Company,')]][1]//button[@aria-label='Easy Apply to this job']"):
                        try: 
                            try:
                                errored = ""
                                modal = find_by_class(driver, "jobs-easy-apply-modal")
                                wait_span_click(modal, "Next", 1)
                                # if description != "Unknown":
                                #     resume = create_custom_resume(description)
                                resume = "Previous resume"
                                next_button = True
                                questions_list = set()
                                next_counter = 0
                                while next_button:
                                    next_counter += 1
                                    if next_counter >= 15: 
                                        if pause_at_failed_question:
                                            screenshot(driver, job_id, "Needed manual intervention for failed question")
                                            pyautogui.alert("Couldn't answer one or more questions.\nPlease click \"Continue\" once done.\nDO NOT CLICK Back, Next or Review button in LinkedIn.\n\n\n\n\nYou can turn off \"Pause at failed question\" setting in config.py", "Help Needed", "Continue")
                                            next_counter = 1
                                            continue
                                        if questions_list: print_lg("Stuck for one or some of the following questions...", questions_list)
                                        screenshot_name = screenshot(driver, job_id, "Failed at questions")
                                        errored = "stuck"
                                        raise Exception("Seems like stuck in a continuous loop of next, probably because of new questions.")
                                    questions_list = answer_questions(modal, questions_list, work_location, job_description=description)
                                    if use_AI_for_resume and not uploaded:
                                        if modal.find_elements(By.NAME, "file"):
                                            uploaded, resume = upload_optimized_resume(modal, default_resume_docx_path, description, job_id, title, first_name, last_name)
                                            if not uploaded:
                                                raise ResumeUploadError("No verified resume was attached; discarding application.")
                                    elif useNewResume and not uploaded:
                                        uploaded, resume = upload_resume(modal, default_resume_path)
                                    try: next_button = modal.find_element(By.XPATH, './/span[normalize-space(.)="Review"]') 
                                    except NoSuchElementException:  next_button = modal.find_element(By.XPATH, './/button[contains(span, "Next")]')
                                    try: next_button.click()
                                    except ElementClickInterceptedException: break    # Happens when it tries to click Next button in About Company photos section
                                    buffer(click_gap)

                            except NoSuchElementException: errored = "nose"
                            finally:
                                if use_AI_for_resume and not uploaded:
                                    raise ResumeUploadError("No verified resume was attached; discarding application.")
                                if questions_list and errored != "stuck": 
                                    print_lg("Answered the following questions...", questions_list)
                                    print("\n\n" + "\n".join(str(question) for question in questions_list) + "\n\n")
                                wait_span_click(driver, "Review", 1, scrollTop=True)
                                cur_pause_before_submit = pause_before_submit
                                if errored != "stuck" and cur_pause_before_submit:
                                    decision = pyautogui.confirm('1. Please verify your information.\n2. If you edited something, please return to this final screen.\n3. DO NOT CLICK "Submit Application".\n\n\n\n\nYou can turn off "Pause before submit" setting in config.py\nTo TEMPORARILY disable pausing, click "Disable Pause"', "Confirm your information",["Disable Pause", "Discard Application", "Submit Application"])
                                    if decision == "Discard Application": raise Exception("Job application discarded by user!")
                                    pause_before_submit = False if "Disable Pause" == decision else True
                                    # try_xp(modal, ".//span[normalize-space(.)='Review']")
                                follow_company(modal)
                                checkpoint_job(job_id, "submitting", "Submission requested; verify LinkedIn if interrupted")
                                if wait_span_click(driver, "Submit application", 2, scrollTop=True): 
                                    date_applied = datetime.now()
                                    checkpoint_job(job_id, "applied", "Easy Apply submitted")
                                    if not wait_span_click(driver, "Done", 2): actions.send_keys(Keys.ESCAPE).perform()
                                elif errored != "stuck" and cur_pause_before_submit and "Yes" in pyautogui.confirm("You submitted the application, didn't you 😒?", "Failed to find Submit Application!", ["Yes", "No"]):
                                    date_applied = datetime.now()
                                    checkpoint_job(job_id, "applied", "Easy Apply submitted")
                                    wait_span_click(driver, "Done", 2)
                                else:
                                    print_lg("Since, Submit Application failed, discarding the job application...")
                                    # if screenshot_name == "Not Available":  screenshot_name = screenshot(driver, job_id, "Failed to click Submit application")
                                    # else:   screenshot_name = [screenshot_name, screenshot(driver, job_id, "Failed to click Submit application")]
                                    raise Exception("Failed to submit application")


                        except Exception as e:
                            print_lg("Failed to Easy apply!")
                            # print_lg(e)
                            critical_error_log("Somewhere in Easy Apply process",e)
                            failed_job(job_id, job_link, resume, date_listed, "Problem in Easy Applying", e, application_link, screenshot_name)
                            failed_count += 1
                            if date_applied == "Pending":
                                discard_job()
                                continue
                            print_lg("Submission succeeded; recording applied history despite a later UI error")
                    else:
                        # Case 2: Apply externally
                        skip, application_link, tabs_count = external_apply(pagination_element, job_id, job_link, resume, date_listed, application_link, screenshot_name)
                        if dailyEasyApplyLimitReached:
                            print_lg("\n###############  Daily application limit for Easy Apply is reached!  ###############\n")
                            checkpoint_job(job_id, "skipped", "Daily Easy Apply limit reached")
                            manifest.interrupt("daily_easy_apply_limit")
                            return
                        if skip:
                            checkpoint_job(job_id, "skipped", "External apply unavailable or Easy Apply required")
                            continue
                        checkpoint_job(job_id, "collected", "External application link collected; not submitted")

                    submitted_jobs(job_id, title, company, work_location, work_style, description, experience_required, skills, hr_name, hr_link, resume, reposted, date_listed, date_applied, job_link, application_link, questions_list, connect_request)
                    if uploaded:   useNewResume = False

                    print_lg(f'Successfully saved "{title} | {company}" job. Job ID: {job_id} info')
                    if application_link == "Easy Applied": easy_applied_count += 1
                    else:   external_jobs_count += 1
                    if date_applied != "Pending":
                        applied_jobs.add(job_id)
                    if result_sink:
                        result_sink(application_outcome(manifest, spec, job_id))



                if application_budget is not None and application_budget.stop_if_reached(manifest, spec):
                    return
                if manifest.quota_met(spec) or manifest.has_uncertain_submission(spec):
                    break
                # Switching to next page
                if pagination_element == None:
                    print_lg("Couldn't find pagination element, probably at the end page of results!")
                    break
                if not next_search_page(driver, current_page or 1):
                    print_lg(f"\n>-> Didn't find Page {(current_page or 1)+1}. Probably at the end page of results!\n")
                    break
                print_lg(f"\n>-> Now on Page {(current_page or 1)+1} \n")
                wait_for_search_results(job_listings)

            if manifest.has_uncertain_submission(spec):
                row = manifest.query(spec.query_id)
                row["status"], row["stop_reason"] = "pending", "submission_uncertain"
                manifest.save()
            else:
                manifest.finish_query(spec, "quota_met" if manifest.quota_met(spec) else "results_exhausted")
            if result_sink:
                for job_id in manifest.query(spec.query_id)["jobs"]:
                    result_sink(application_outcome(manifest, spec, job_id))
        except Exception as e:
            from modules.linkedin_search import LocationSelectionError
            diagnostics = getattr(e, "diagnostics", None)
            if diagnostics is not None:
                manifest.record_mode(spec, spec.mode, warnings=[str(e)],
                                     diagnostics=diagnostics() if callable(diagnostics) else diagnostics)
            if isinstance(e, LocationSelectionError) or diagnostics is not None:
                empty = []
                if isinstance(e, LocationSelectionError):
                    manifest.query(spec.query_id)["warnings"].append(f"Configured search location was not confirmed: {e}")
            else:
                empty = search_results_ready(driver) == "empty"
            if empty:
                manifest.finish_query(spec, "results_exhausted")
            else:
                if active_job_id:
                    checkpoint_job(active_job_id, "failed", f"Query interrupted ({type(e).__name__})")
                row = manifest.query(spec.query_id)
                row["status"], row["stop_reason"] = "pending", f"search_error:{type(e).__name__}"
                manifest.save()
                print_lg("Search interrupted; incomplete query will resume next run")
                critical_error_log("In Applier", e)


def apply_to_jobs(legacy_terms: list[str], *, prepared_specs=None, selected_jobs=None, result_sink=None, job_limit=None, application_budget=None):
    from modules.search_planner import role_priority
    global active_manifest, active_search, active_result_sink, active_application_budget
    # globals includes active date/sort cycling; filters still originate only in config/search.py.
    config = dict(globals(), search_terms=list(legacy_terms))
    profile = {key: value for key, value in vars(search_profile).items() if not key.startswith("_")}
    if prepared_specs is not None and not prepared_specs:
        return None
    deterministic = prepared_specs if prepared_specs is not None else build_search_plan(dict(profile, ai_query_refinement_enabled=False), config, warn=print_lg)
    configuration_id = plan_fingerprint(deterministic, profile)
    if selected_jobs is not None:
        import hashlib
        import json
        selection = {key: sorted(str(job["linkedin_id"]) for job in jobs) for key, jobs in selected_jobs.items()}
        configuration_id += ":selected:" + hashlib.sha256(json.dumps(selection, sort_keys=True).encode()).hexdigest()
    with file_lock(os.path.join(profile["search_state_dir"], ".runner.lock")):
        manifest = SearchManifest.find_resume(profile["search_state_dir"], configuration_id) if profile["resume_search_enabled"] else None
        if manifest is None:
            refiner = None if prepared_specs is not None else make_refiner(os.getenv("OPENAI_API_KEY") or llm_api_key, llm_api_url, llm_model, print_lg) if profile["ai_query_refinement_enabled"] else None
            specs = prepared_specs if prepared_specs is not None else build_search_plan(profile, config, refine=refiner, warn=print_lg)
            if randomize_search_order:
                from itertools import groupby
                ordered = []
                for _, group in groupby(specs, key=lambda spec: spec.pipeline_context.get("priority_tier", 4) if spec.pipeline_context else role_priority(spec.classic_query)):
                    group = list(group)
                    shuffle(group)
                    ordered.extend(group)
                specs = ordered
            manifest = SearchManifest.create(profile["search_state_dir"], specs, configuration_id)
        active_manifest = manifest
        active_result_sink = result_sink
        previous_budget = globals().get("active_application_budget")
        active_application_budget = application_budget
        try:
            if application_budget is not None:
                manifest.data["invocation_application_limit"] = application_budget.limit
                manifest.data["invocation_applied_count"] = application_budget.count
                manifest.save()
            print_lg(f"Search run: {manifest.data['run_id']} ({manifest.path})")
            if selected_jobs is None and result_sink is None and job_limit is None and application_budget is None:
                execute_search_plan(manifest)
            else:
                options = dict(selected_jobs=selected_jobs, result_sink=result_sink, job_limit=job_limit)
                if application_budget is not None:
                    options["application_budget"] = application_budget
                execute_search_plan(manifest, **options)
            stop_reason = manifest.data.get("stop_reason")
            manifest.finish()
            if stop_reason in {"application_limit_reached", "submission_uncertain"}:
                manifest.data["stop_reason"] = stop_reason
                manifest.save()
                if application_budget is not None:
                    print_lg(f"Stopping: {stop_reason}; confirmed submissions this invocation: {application_budget.count}, cap: {application_budget.limit}")
            return manifest
        except BaseException as error:
            manifest.interrupt(type(error).__name__)
            raise
        finally:
            active_manifest = active_search = None
            active_result_sink = None
            active_application_budget = previous_budget


def run(total_runs: int, *, application_budget=None) -> int:
    if dailyEasyApplyLimitReached or application_budget is not None and application_budget.stopped:
        return total_runs
    print_lg("\n########################################################################################################################\n")
    print_lg(f"Date and Time: {datetime.now()}")
    print_lg(f"Cycle number: {total_runs}")
    print_lg(f"Currently looking for jobs posted within '{date_posted}' and sorting them by '{sort_by}'")
    options = {} if application_budget is None else {"application_budget": application_budget}
    apply_to_jobs(search_terms, **options)
    print_lg("########################################################################################################################\n")
    # if not dailyEasyApplyLimitReached:
    #     print_lg("Sleeping for 10 min...")
    #     sleep(300)
    #     print_lg("Few more min... Gonna start with in next 5 min...")
    #     sleep(300)
    buffer(3)
    return total_runs + 1



chatGPT_tab = False
linkedIn_tab = False

def main() -> None:
    load_runtime()
    application_budget = ApplicationBudget(globals().get("max_applications_per_run", 1))
    initialize_browser()
    try:
        global linkedIn_tab, tabs_count, useNewResume, aiClient
        alert_title = "Error Occurred. Closing Browser!"
        total_runs = 1        
        validate_config()
        
        if not os.path.exists(default_resume_path):
            pyautogui.alert(text='Your default resume "{}" is missing! Please update it\'s folder path "default_resume_path" in config.py\n\nOR\n\nAdd a resume with exact name and path (check for spelling mistakes including cases).\n\n\nFor now the bot will continue using your previous upload from LinkedIn!'.format(default_resume_path), title="Missing Resume", button="OK")
            useNewResume = False
        
        # Login to LinkedIn
        tabs_count = len(driver.window_handles)
        driver.get("https://www.linkedin.com/login")
        if not is_logged_in_LN(): login_LN()
        
        linkedIn_tab = driver.current_window_handle

        # # Login to ChatGPT in a new tab for resume customization
        # if use_resume_generator:
        #     try:
        #         driver.switch_to.new_window('tab')
        #         driver.get("https://chat.openai.com/")
        #         if not is_logged_in_GPT(): login_GPT()
        #         open_resume_chat()
        #         global chatGPT_tab
        #         chatGPT_tab = driver.current_window_handle
        #     except Exception as e:
        #         print_lg("Opening OpenAI chatGPT tab failed!")
        if use_AI:
            aiClient = ai_create_openai_client()

        # Start applying to jobs
        driver.switch_to.window(linkedIn_tab)
        total_runs = run(total_runs, application_budget=application_budget)
        while run_non_stop and not application_budget.stopped:
            if cycle_date_posted:
                date_options = ["Any time", "Past month", "Past week", "Past 24 hours"]
                global date_posted
                date_posted = date_options[date_options.index(date_posted)+1 if date_options.index(date_posted)+1 > len(date_options) else -1] if stop_date_cycle_at_24hr else date_options[0 if date_options.index(date_posted)+1 >= len(date_options) else date_options.index(date_posted)+1]
            if alternate_sortby:
                global sort_by
                sort_by = "Most recent" if sort_by == "Most relevant" else "Most relevant"
                total_runs = run(total_runs, application_budget=application_budget)
                sort_by = "Most recent" if sort_by == "Most relevant" else "Most relevant"
            total_runs = run(total_runs, application_budget=application_budget)
            if dailyEasyApplyLimitReached:
                break
        

    except NoSuchWindowException:   pass
    except Exception as e:
        critical_error_log("In Applier Main", e)
        pyautogui.alert(e,alert_title)
    finally:
        print_lg("\n\nTotal runs:                     {}".format(total_runs))
        print_lg("Jobs Easy Applied:              {}".format(easy_applied_count))
        print_lg(f"Confirmed this invocation:      {application_budget.count} (cap: {application_budget.limit})")
        print_lg("External job links collected:   {}".format(external_jobs_count))
        print_lg("                              ----------")
        print_lg("Total applied or collected:     {}".format(easy_applied_count + external_jobs_count))
        print_lg("\nFailed jobs:                    {}".format(failed_count))
        print_lg("Irrelevant jobs skipped:        {}\n".format(skip_count))
        if randomly_answered_questions: print_lg("\n\nQuestions randomly answered:\n  {}  \n\n".format(";\n".join(str(question) for question in randomly_answered_questions)))
        quote = choice([
            "You're one step closer than before.", 
            "All the best with your future interviews.", 
            "Keep up with the progress. You got this.", 
            "If you're tired, learn to take rest but never give up.",
            "Success is not final, failure is not fatal: It is the courage to continue that counts. - Winston Churchill",
            "Believe in yourself and all that you are. Know that there is something inside you that is greater than any obstacle. - Christian D. Larson",
            "Every job is a self-portrait of the person who does it. Autograph your work with excellence.",
            "The only way to do great work is to love what you do. If you haven't found it yet, keep looking. Don't settle. - Steve Jobs",
            "Opportunities don't happen, you create them. - Chris Grosser",
            "The road to success and the road to failure are almost exactly the same. The difference is perseverance.",
            "Obstacles are those frightful things you see when you take your eyes off your goal. - Henry Ford",
            "The only limit to our realization of tomorrow will be our doubts of today. - Franklin D. Roosevelt"
            ])
        msg = f"\n{quote}\n\n\nCheers"
        pyautogui.alert(msg, "Exiting..")
        print_lg(msg,"Closing the browser...")
        if tabs_count >= 10:
            msg = "NOTE: IF YOU HAVE MORE THAN 10 TABS OPENED, PLEASE CLOSE OR BOOKMARK THEM!\n\nOr it's highly likely that application will just open browser and not do anything next time!" 
            pyautogui.alert(msg,"Info")
            print_lg("\n"+msg)
        ai_close_openai_client(aiClient)
        # try: driver.quit()
        # except Exception as e: critical_error_log("When quitting...", e)

# write a wrapper function to run the main function that loops until the user closes the browser
def run_bot():
    # main already implements configured continuous cycles. A one-shot smoke run stays one-shot.
    main()


def run_pipeline(request):
    """Shared durable backend for job_pipeline and explicit runAiBot modes."""
    from contextlib import redirect_stdout
    from copy import deepcopy
    import sys
    from config import search as search_config
    from modules.job_pipeline.models import LinkedInRunRequest, StageResult, write_artifact
    from modules.job_pipeline.store import PipelineStore
    from modules.job_pipeline.service import load_inputs
    from modules.job_pipeline.linkedin import mapping, prepare_specs, selected_specs

    global current_pipeline_run_id, current_pipeline_blocked_ids, linkedIn_tab, tabs_count, aiClient, pause_before_submit
    if not isinstance(request, LinkedInRunRequest):
        raise ValueError("run_pipeline expects a LinkedInRunRequest")
    expected = "linkedin_jobs" if request.mode == "apply" else "verified_roles"
    output_stage = "linkedin_jobs" if request.mode == "search" else "applications"
    with PipelineStore(request.db_path) as store:
        artifacts = load_inputs(store, request.input_sets, expected)
        inputs = [record for artifact in artifacts for record in artifact.records] if artifacts else store.load_set(expected, request.set_name)
        inputs = list({record["id"]: record for record in inputs}.values())
        if not artifacts and not inputs:
            raise ValueError(f"No {expected} available; supply --input or populate the named set first")
        parent_ids = list(dict.fromkeys(f"{artifact.stage}:{artifact.set_name}" for artifact in artifacts)) or [expected + ":" + request.set_name]
        config, profile = mapping(search_config), mapping(search_profile)
        application_budget = ApplicationBudget(config.get("max_applications_per_run", 1)) if request.mode != "search" else None
        # Existing newer closure evidence wins over descriptions embedded in old exports.
        if request.mode == "apply":
            for job in inputs:
                job["career_roles"] = [store.resolve_record("verified_roles", role["id"]) or role for role in job.get("career_roles", [])]
            specs, selection, errors = selected_specs(inputs, profile, config)
        else:
            specs, errors = prepare_specs(inputs, profile, config)
            selection = None
        for spec in specs:
            spec.pipeline_context["set_name"] = request.set_name
        run_id = store.begin_run(output_stage, request.set_name, parent_ids, {"mode": request.mode, "limit": request.limit, "max_applications_per_run": application_budget.limit if application_budget is not None else None, "filters": config, "profile": profile})
        delta, scan_delta = [], []
        current_pipeline_run_id = run_id
        current_pipeline_blocked_ids = set()
        selection_by_id = {str(row.get("linkedin_id")): row for rows in (selection or {}).values() for row in rows}

        def save_match(record):
            record = dict(record, search_run_id=run_id, pipeline_run_id=run_id, pipeline_set=request.set_name)
            scan_delta.extend(store.upsert_many("linkedin_jobs", request.set_name, [record], run_id))

        def save_outcome(record):
            original = selection_by_id.get(record["job_id"], {})
            record = {**deepcopy(original), **record, "pipeline_run_id": run_id, "pipeline_set": request.set_name,
                      "discovery_run_id": original.get("search_run_id")}
            delta.extend(store.upsert_many("applications", request.set_name, [record], run_id))

        def protect_applications(current_specs, current_selection):
            runnable = False
            for query_id, jobs in current_selection.items():
                for job in jobs:
                    previous = store.application_for_job(str(job["linkedin_id"]))
                    if previous and previous.get("status") in {"applied", "submitting"}:
                        current_pipeline_blocked_ids.add(str(job["linkedin_id"]))
                        delta.extend(store.upsert_many("applications", request.set_name, [previous], run_id))
                        if previous["status"] == "submitting":
                            errors.append({"record_id": job["id"], "code": "submission_uncertain", "message": "Verify the earlier submission on LinkedIn before retrying"})
                    else:
                        runnable = True
            # Keep the selected plan stable across resume; the runner skips protected IDs.
            return (current_specs if runnable else []), current_selection

        if request.mode == "apply":
            selected_ids = set(selection_by_id)
            for job in inputs:
                job_id = str(job.get("linkedin_id", ""))
                if job_id.isdigit() and job_id not in selected_ids:
                    save_outcome(dict(job, job_id=job_id, eligible=False, status="skipped", reason="Verified parent is closed, stale, excluded, or inconsistent"))
            specs, selection = protect_applications(specs, selection)

        status, remaining_work = "complete", False
        try:
            if specs:
                # Runtime diagnostics go to stderr; stdout remains one portable JSON result.
                with redirect_stdout(sys.stderr):
                    load_runtime(request.mode)
                    if request.mode != "search":
                        validate_config()
                        # Pipeline applications retain a visible final review even in background configuration.
                        pause_before_submit = True
                    initialize_browser(background=False if request.mode != "search" else None)
                    tabs_count = len(driver.window_handles)
                    driver.get("https://www.linkedin.com/login")
                    if not is_logged_in_LN():
                        login_LN()
                    if not is_logged_in_LN():
                        raise ValueError("LinkedIn authentication is required")
                    linkedIn_tab = driver.current_window_handle
                    if request.mode != "apply":
                        checkpoints = {spec.query_id: store.get_checkpoint("linkedin-search:" + spec.query_id, request.set_name) for spec in specs}
                        _, scan_errors = collect_linkedin_jobs(
                            specs, limit=request.limit, result_sink=save_match, checkpoints=checkpoints,
                            checkpoint_sink=lambda query_id, value: store.save_checkpoint("linkedin-search:" + query_id, request.set_name, value),
                            refresh=request.refresh,
                        )
                        errors.extend(scan_errors)
                    if request.mode == "search-and-apply":
                        parent_roles = {role["id"] for spec in specs for role in spec.pipeline_context["career_roles"]}
                        matches = [record for record in store.load_set("linkedin_jobs", request.set_name) if parent_roles.intersection(record.get("career_job_ids", []))]
                        specs, selection, preparation_errors = selected_specs(matches, profile, config)
                        errors.extend(preparation_errors)
                        selection_by_id.update({str(row["linkedin_id"]): row for rows in selection.values() for row in rows})
                        for spec in specs:
                            spec.pipeline_context["set_name"] = request.set_name
                        specs, selection = protect_applications(specs, selection)
                    if request.mode != "search" and specs:
                        if use_AI:
                            aiClient = ai_create_openai_client()
                        manifest = apply_to_jobs([], prepared_specs=specs, selected_jobs=selection, result_sink=save_outcome, job_limit=request.limit, application_budget=application_budget)
                        if manifest and manifest.data["status"] != "complete":
                            remaining_work = True
                            if manifest.data.get("stop_reason") not in {"work_limit", "application_limit_reached"}:
                                errors.append({"code": "application_interrupted", "message": manifest.data.get("stop_reason") or "An incomplete query requires resume or submission verification", "search_run_id": manifest.data["run_id"]})
            status = "partial" if errors or remaining_work else "complete"
        except KeyboardInterrupt:
            errors.append({"code": "KeyboardInterrupt", "message": "Run interrupted; durable checkpoints were retained", "retryable": True})
            status = "interrupted"
        except Exception as error:
            errors.append({"code": type(error).__name__, "message": str(error), "retryable": True})
            status = "partial" if delta or scan_delta else "failed"
        finally:
            store.finish_run(run_id, status, errors)
            current_pipeline_run_id = None
            current_pipeline_blocked_ids = set()
            if aiClient:
                ai_close_openai_client(aiClient)
                aiClient = None
        cumulative = store.load_set(output_stage, request.set_name)
        changed_ids = {row["id"] for row in (scan_delta if output_stage == "linkedin_jobs" else delta)}
        result = StageResult.create(output_stage, request.set_name, run_id, cumulative,
                                    [row for row in cumulative if row["id"] in changed_ids], errors, parent_ids)
        if request.output_path:
            write_artifact(result, request.output_path)
        return result


def cli_main(argv=None):
    import argparse
    import json
    import sys
    from config import job_pipeline as config
    from job_pipeline import _positive
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        run_bot()
        return 0
    parser = argparse.ArgumentParser(description="Legacy bot or the shared persisted LinkedIn pipeline.", allow_abbrev=False)
    parser.add_argument("--mode", choices=("search", "apply", "search-and-apply"), default="search")
    parser.add_argument("--diagnose-search", action="store_true",
                        help="Read-only configured-search diagnostic; collect card metadata without applying")
    parser.add_argument("--input", action="append", default=[], metavar="JSON_OR_SET")
    parser.add_argument("--set", dest="set_name", default=config.default_set)
    parser.add_argument("--output", dest="output_path")
    parser.add_argument("--limit", type=_positive, default=None)
    parser.add_argument("--db", dest="db_path", default=config.db_path)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args(argv)
    if args.diagnose_search:
        incompatible = {"--mode", "--input", "--set", "--db", "--refresh"}
        if any(argument.partition("=")[0] in incompatible for argument in argv):
            parser.error("--diagnose-search accepts only --limit and --output")
        from modules.search_diagnostics import run_diagnostic
        try:
            result = run_diagnostic(sys.modules[__name__], limit=args.limit or 5, output_path=args.output_path)
        except (ValueError, OSError) as error:
            print(f"runAiBot: {error}", file=sys.stderr)
            return 2
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 1 if result.get("errors") else 0
    from modules.job_pipeline.models import LinkedInRunRequest, StageResult, write_artifact
    from modules.job_pipeline.service import load_inputs
    from modules.job_pipeline.store import PipelineStore
    args.limit = args.limit or config.default_limit
    if args.mode == "apply" and args.refresh:
        parser.error("--refresh is available for search modes only; application history is retained")
    try:
        expected = "linkedin_jobs" if args.mode == "apply" else "verified_roles"
        with PipelineStore(args.db_path) as store:
            artifacts = load_inputs(store, args.input, expected)
        request = LinkedInRunRequest(args.mode, [item.to_dict() for item in artifacts], args.set_name,
                                     args.output_path, args.limit, args.db_path, args.refresh)
        result = StageResult.from_dict(run_pipeline(request))
        if args.output_path:
            write_artifact(result, args.output_path)
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
        return 1 if result.errors else 0
    except (ValueError, OSError, json.JSONDecodeError) as error:
        print(f"runAiBot: {error}", file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(cli_main())
