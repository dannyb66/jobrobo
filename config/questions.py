###################################################### APPLICATION INPUTS ######################################################


# >>>>>>>>>>> Easy Apply Questions & Inputs <<<<<<<<<<<

# Give an relative path of your default resume to be uploaded. If file in not found, will continue using your previously uploaded resume in LinkedIn.
default_resume_path = "all resumes/default/resume.pdf"      # (In Development)
default_resume_docx_path = "all resumes/default/resume.docx"      # (In Development)
# default_resume_path = "all resumes/default/pm_resume.pdf"      # (In Development)
# default_resume_docx_path = "all resumes/default/pm_resume.docx"      # (In Development)

# What do you want to answer for questions that ask about years of experience you have, this is different from current_experience? 
years_of_experience = "6"          # A number in quotes Eg: "0","1","2","3","4", etc.

# Do you need visa sponsorship now or in future?
require_visa = "No"               # "Yes" or "No"

# What is the link to your portfolio website, leave it empty as "", if you want to leave this question unanswered
website = ""                        # "www.example.bio" or "" and so on....

# Please provide the link to your LinkedIn profile.
linkedIn = "https://www.linkedin.com/in/dannybasavaraju/"       # "https://www.linkedin.com/in/example" or "" and so on...

# What is the status of your citizenship? # If left empty as "", tool will not answer the question. However, note that some companies make it compulsory to be answered
# Valid options are: "U.S. Citizen/Permanent Resident", "Non-citizen allowed to work for any employer", "Non-citizen allowed to work for current employer", "Non-citizen seeking work authorization", "Canadian Citizen/Permanent Resident" or "Other"
us_citizenship = "Non-citizen allowed to work for any employer"



## SOME ANNOYING QUESTIONS BY COMPANIES 🫠 ##

# What to enter in your desired salary question (American and European), What is your expected CTC (South Asian and others)?, only enter in numbers as some companies only allow numbers,
desired_salary = 200000          # 80000, 90000, 100000 or 120000 and so on... Do NOT use quotes
'''
Note: If question has the word "lakhs" in it (Example: What is your expected CTC in lakhs), 
then it will add '.' before last 5 digits and answer. Examples: 
* 2400000 will be answered as "24.00"
* 850000 will be answered as "8.50"
And if asked in months, then it will divide by 12 and answer. Examples:
* 2400000 will be answered as "200000"
* 850000 will be answered as "70833"
'''

# What is your current CTC? Some companies make it compulsory to be answered in numbers...
current_ctc = 150000            # 800000, 900000, 1000000 or 1200000 and so on... Do NOT use quotes
'''
Note: If question has the word "lakhs" in it (Example: What is your current CTC in lakhs), 
then it will add '.' before last 5 digits and answer. Examples: 
* 2400000 will be answered as "24.00"
* 850000 will be answered as "8.50"
# And if asked in months, then it will divide by 12 and answer. Examples:
# * 2400000 will be answered as "200000"
# * 850000 will be answered as "70833"
'''

# (In Development) # Currency of salaries you mentioned. Companies that allow string inputs will add this tag to the end of numbers. Eg: 
# currency = "INR"                 # "USD", "INR", "EUR", etc.

# What is your notice period in days?
notice_period = 30                   # Any number >= 0 without quotes. Eg: 0, 7, 15, 30, 45, etc.
'''
Note: If question has 'month' or 'week' in it (Example: What is your notice period in months), 
then it will divide by 30 or 7 and answer respectively. Examples:
* For notice_period = 66:
  - "66" OR "2" if asked in months OR "9" if asked in weeks
* For notice_period = 15:"
  - "15" OR "0" if asked in months OR "2" if asked in weeks
* For notice_period = 0:
  - "0" OR "0" if asked in months OR "0" if asked in weeks
'''

# Your LinkedIn headline in quotes Eg: "Software Engineer @ Google, Masters in Computer Science", "Recent Grad Student @ MIT, Computer Science"
# linkedin_headline = "Full Stack Developer with Masters in Computer Science and 4+ years of experience" # "Headline" or "" to leave this question unanswered
linkedin_headline = "Software Engineer | Ex-Founding Engineer & CTO | Built Scalable Systems @ Startups - Chill Panda Tech, BYJUS, RIVIGO | IIT Delhi & IIM Calcutta Alum | Bay Area Tech Enthusiast" # "Headline" or "" to leave this question unanswered

# Your summary in quotes, use \n to add line breaks if using single quotes "Summary".You can skip \n if using triple quotes """Summary"""
# linkedin_summary = """
# I'm a Senior Software Engineer at Amazon with Masters in CS and 4+ years of experience in developing and maintaining Full Stack Web applications and cloud solutions. 
# Specialized in React, Node.js, and Python.
# """
linkedin_summary = """
𝗦𝗼𝗳𝘁𝘄𝗮𝗿𝗲 𝗘𝗻𝗴𝗶𝗻𝗲𝗲𝗿 | 𝗔𝗜 & 𝗦𝗰𝗮𝗹𝗮𝗯𝗹𝗲 𝗦𝘆𝘀𝘁𝗲𝗺𝘀 | 𝗘𝘅-𝗙𝗼𝘂𝗻𝗱𝗲𝗿 | 𝗕𝗮𝘆 𝗔𝗿𝗲𝗮

A 𝗳𝘂𝗹𝗹-𝘀𝘁𝗮𝗰𝗸 𝗔𝗜 𝘀𝗼𝗳𝘁𝘄𝗮𝗿𝗲 𝗲𝗻𝗴𝗶𝗻𝗲𝗲𝗿 with 𝗳𝗼𝘂𝗻𝗱𝗲𝗿 𝗲𝘅𝗽𝗲𝗿𝗶𝗲𝗻𝗰𝗲, specializing in 𝗔𝗜-𝗱𝗿𝗶𝘃𝗲𝗻 𝗮𝗽𝗽𝗹𝗶𝗰𝗮𝘁𝗶𝗼𝗻𝘀, 𝘀𝗰𝗮𝗹𝗮𝗯𝗹𝗲 𝗯𝗮𝗰𝗸𝗲𝗻𝗱 𝗮𝗿𝗰𝗵𝗶𝘁𝗲𝗰𝘁𝘂𝗿𝗲𝘀, 𝗮𝗻𝗱 𝗰𝗹𝗼𝘂𝗱-𝗻𝗮𝘁𝗶𝘃𝗲 𝘀𝗼𝗹𝘂𝘁𝗶𝗼𝗻𝘀. Passionate about building high-performance systems that drive business impact at 𝗳𝗮𝘀𝘁-𝗴𝗿𝗼𝘄𝗶𝗻𝗴 𝘀𝘁𝗮𝗿𝘁𝘂𝗽𝘀.

Key Highlights

• 𝗦𝗰𝗮𝗹𝗮𝗯𝗹𝗲 𝗦𝘆𝘀𝘁𝗲𝗺𝘀 & 𝗔𝗜 𝗘𝗻𝗴𝗶𝗻𝗲𝗲𝗿𝗶𝗻𝗴: Architected 𝗔𝗜-𝗽𝗼𝘄𝗲𝗿𝗲𝗱 𝗰𝘂𝘀𝘁𝗼𝗺𝗲𝗿 𝗲𝗻𝗴𝗮𝗴𝗲𝗺𝗲𝗻𝘁 𝗽𝗹𝗮𝘁𝗳𝗼𝗿𝗺𝘀 (yes, multiple!) at Chill Panda Tech, driving 𝟯𝟬% 𝗿𝗲𝘃𝗲𝗻𝘂𝗲 𝗴𝗿𝗼𝘄𝘁𝗵 for clients through 𝗱𝘆𝗻𝗮𝗺𝗶𝗰 𝗽𝗿𝗶𝗰𝗶𝗻𝗴 𝗮𝗹𝗴𝗼𝗿𝗶𝘁𝗵𝗺𝘀 and 𝗿𝗲𝗮𝗹-𝘁𝗶𝗺𝗲 𝗼𝗿𝗱𝗲𝗿 𝗽𝗿𝗼𝗰𝗲𝘀𝘀𝗶𝗻𝗴 𝗽𝗶𝗽𝗲𝗹𝗶𝗻𝗲𝘀.
• 𝗧𝗲𝗰𝗵 𝗟𝗲𝗮𝗱𝗲𝗿𝘀𝗵𝗶𝗽 𝗶𝗻 𝗛𝗶𝗴𝗵-𝗚𝗿𝗼𝘄𝘁𝗵 𝗦𝘁𝗮𝗿𝘁𝘂𝗽𝘀: Led 𝗳𝘂𝗹𝗹-𝘀𝘁𝗮𝗰𝗸 𝗱𝗲𝘃𝗲𝗹𝗼𝗽𝗺𝗲𝗻𝘁 at Chill Panda Tech & Quantgro, delivering a 𝗺𝘂𝗹𝘁𝗶-𝘁𝗲𝗻𝗮𝗻𝘁 𝗦𝗮𝗮𝗦 𝗽𝗹𝗮𝘁𝗳𝗼𝗿𝗺 𝘄𝗶𝘁𝗵 𝟵𝟵.𝟵% 𝘂𝗽𝘁𝗶𝗺𝗲 and supporting $𝟭𝗠+ 𝗶𝗻 𝘁𝗿𝗮𝗻𝘀𝗮𝗰𝘁𝗶𝗼𝗻𝘀.
• 𝗖𝗹𝗼𝘂𝗱 & 𝗗𝗶𝘀𝘁𝗿𝗶𝗯𝘂𝘁𝗲𝗱 𝗦𝘆𝘀𝘁𝗲𝗺𝘀: Designed and deployed 𝗺𝗶𝗰𝗿𝗼𝘀𝗲𝗿𝘃𝗶𝗰𝗲𝘀-𝗯𝗮𝘀𝗲𝗱 𝗶𝗻𝗳𝗿𝗮𝘀𝘁𝗿𝘂𝗰𝘁𝘂𝗿𝗲𝘀 on 𝗔𝗪𝗦 & 𝗚𝗖𝗣, enabling rapid feature rollouts and seamless scalability.
• 𝗛𝗮𝗻𝗱𝘀-𝗼𝗻 𝗖𝗼𝗱𝗶𝗻𝗴 & 𝗣𝗿𝗼𝗱𝘂𝗰𝘁 𝗕𝘂𝗶𝗹𝗱𝗶𝗻𝗴: Strong expertise in 𝗣𝘆𝘁𝗵𝗼𝗻, 𝗡𝗼𝗱𝗲.𝗷𝘀, 𝗥𝗲𝗮𝗰𝘁, 𝗡𝗲𝘅𝘁.𝗷𝘀, 𝗞𝘂𝗯𝗲𝗿𝗻𝗲𝘁𝗲𝘀, 𝗮𝗻𝗱 𝗱𝗶𝘀𝘁𝗿𝗶𝗯𝘂𝘁𝗲𝗱 𝗱𝗮𝘁𝗮𝗯𝗮𝘀𝗲𝘀 for scalable software development.
• 𝗕𝗿𝗶𝗱𝗴𝗶𝗻𝗴 𝗕𝘂𝘀𝗶𝗻𝗲𝘀𝘀 & 𝗧𝗲𝗰𝗵𝗻𝗼𝗹𝗼𝗴𝘆: With a 𝗕𝗧𝗲𝗰𝗵 𝗳𝗿𝗼𝗺 𝗜𝗜𝗧 𝗗𝗲𝗹𝗵𝗶 and 𝗠𝗕𝗔 𝗳𝗿𝗼𝗺 𝗜𝗜𝗠 𝗖𝗮𝗹𝗰𝘂𝘁𝘁𝗮, I bring a 𝘂𝗻𝗶𝗾𝘂𝗲 𝗯𝗹𝗲𝗻𝗱 𝗼𝗳 𝘁𝗲𝗰𝗵𝗻𝗶𝗰𝗮𝗹 𝗱𝗲𝗽𝘁𝗵 𝗮𝗻𝗱 𝗯𝘂𝘀𝗶𝗻𝗲𝘀𝘀 𝗮𝗰𝘂𝗺𝗲𝗻, making me a strong fit for 𝘁𝗲𝗰𝗵-𝗱𝗿𝗶𝘃𝗲𝗻 𝘀𝘁𝗮𝗿𝘁𝘂𝗽 𝗲𝗻𝘃𝗶𝗿𝗼𝗻𝗺𝗲𝗻𝘁𝘀.

What I’m Looking For

Excited to join a 𝗕𝗮𝘆 𝗔𝗿𝗲𝗮 𝘀𝘁𝗮𝗿𝘁𝘂𝗽 where I can:
• Build and scale 𝗔𝗜-𝗽𝗼𝘄𝗲𝗿𝗲𝗱 𝗽𝗿𝗼𝗱𝘂𝗰𝘁𝘀 from the ground up.
• Solve complex engineering challenges in 𝗔𝗜/𝗠𝗟, 𝗰𝗹𝗼𝘂𝗱 𝗰𝗼𝗺𝗽𝘂𝘁𝗶𝗻𝗴 𝗮𝗻𝗱 𝗱𝗶𝘀𝘁𝗿𝗶𝗯𝘂𝘁𝗲𝗱 𝘀𝘆𝘀𝘁𝗲𝗺𝘀.
• Work with 𝗳𝗮𝘀𝘁-𝗺𝗼𝘃𝗶𝗻𝗴 𝘁𝗲𝗮𝗺𝘀 in 𝗔𝗜, 𝗦𝗮𝗮𝗦, 𝗼𝗿 𝗱𝗲𝗲𝗽 𝘁𝗲𝗰𝗵 startups.

I’m actively sharing my work on 𝗚𝗶𝘁𝗛𝘂𝗯 & 𝗟𝗶𝗻𝗸𝗲𝗱𝗜𝗻 to connect with the best minds in tech. Let’s build something impactful!
"""

'''
Note: If left empty as "", the tool will not answer the question. However, note that some companies make it compulsory to be answered. Use \n to add line breaks.
''' 

# Your cover letter in quotes, use \n to add line breaks if using single quotes "Cover Letter".You can skip \n if using triple quotes """Cover Letter""" (This question makes sense though)
cover_letter = """
Cover Letter
"""
##> ------ Dheeraj Deshwal : dheeraj9811 Email:dheeraj20194@iiitd.ac.in/dheerajdeshwal9811@gmail.com - Feature ------

# Your user_information_all letter in quotes, use \n to add line breaks if using single quotes "user_information_all".You can skip \n if using triple quotes """user_information_all""" (This question makes sense though)
# We use this to pass to AI to generate answer from information , Assuing Information contians eg: resume  all the information like name, experience, skills, Country, any illness etc. 
user_information_all ="""
User Information
"""
##<
'''
Note: If left empty as "", the tool will not answer the question. However, note that some companies make it compulsory to be answered. Use \n to add line breaks.
''' 

# Name of your most recent employer
recent_employer = "Not Applicable" # "", "Lala Company", "Google", "Snowflake", "Databricks"

# Example question: "On a scale of 1-10 how much experience do you have building web or mobile applications? 1 being very little or only in school, 10 being that you have built and launched applications to real users"
confidence_level = "8"             # Any number between "1" to "10" including 1 and 10, put it in quotes ""
##



# >>>>>>>>>>> RELATED SETTINGS <<<<<<<<<<<

## Allow Manual Inputs
# Should the tool pause before every submit application during easy apply to let you check the information?
pause_before_submit = True         # True or False, Note: True or False are case-sensitive
'''
Note: Will be treated as False if `run_in_background = True`
'''

# Should the tool pause if it needs help in answering questions during easy apply?
# Note: If set as False will answer randomly...
pause_at_failed_question = True    # True or False, Note: True or False are case-sensitive
'''
Note: Will be treated as False if `run_in_background = True`
'''
##

# Do you want to overwrite previous answers?
overwrite_previous_answers = False # True or False, Note: True or False are case-sensitive
