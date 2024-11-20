#!/usr/bin/python3
import re
import os
import sys
from github import Github
from github import GithubException


def check_codeowners_file_pr(repo, pr_number):
    """Determines if CODEOWNERS file is in the compare branch of the PR."""
    try:
        pr = repo.get_pull(pr_number)
        commits = pr.get_commits()
    except GithubException as error:
        print(f'Error checking for CODEOWENRS file in PR: {error}')
        exit(1)
    return 'CODEOWNERS' in [file.filename for commit in commits for file in commit.files] 

def check_for_codeowners_file_branch(repo):
    """Determines if CODEOWNERS file is in the base branch."""
    try: 
        repo_contents = repo.get_contents('/')
    except GithubException as error:
        print(f'Error checking for CODEOWENRS file in base branch: {error}')
        exit(1)
    return 'CODEOWNERS' in [content.name for content in repo_contents]

def get_codeowner_lines_dict(contents):
    """Returns dictionary of lines with line #. {'line_#': 'line'}"""
    # Split by \n, remove empty lines
    content_array = list(filter(None, [content for content in contents.split('\n')]))
    return dict((i, x) for i, x in enumerate(content_array, 1))

def check_if_comment_or_header(codeowner_line):
    return codeowner_line[0] == '#' or codeowner_line[0] == '['

def separate_line_codeowners(codeowner_line):
    """Returns array of a line split on whitespace."""
    return list(filter(None, codeowner_line.split(' ')))

def check_for_splat(first_element):
    return first_element == '*'

def get_regex(regex_type):
    """ First element regex should to be more flexible for possibility
    of extra characters. This will get caught later in the 
    codeowner regex check, and will have better logging. """
    first_element_regex = {
    'email': "^\S*\.[a-z]+\@sailpoint\.com$",
    'team': "^\@\S*[a-z\-]+\/\S+$",
    'collaborator': "^\S*[a-z0-9]+-[a-z0-9\-]+$",
    }
    codeowner_regex = {
    'email': "^[a-z]+\.[a-z]+\@sailpoint\.com$",
    'team': "^\@[a-z\-]+\/[^@]\S+$",
    'collaborator': "^\@[a-z0-9]+-[a-z0-9\-]+$",
    }
    return codeowner_regex if regex_type == 'codeowner_regex' else first_element_regex

def check_codeowner_regex(codeowner, regex):
    for key, value in regex.items():
        if re.fullmatch(value, codeowner):
            return key
    return False
    
def get_codeowners_only(codeowners_content, branch):
    """ Parse through lines of codeowner dictionary to 
    identify lines to skip and lines with syntax errors
    related to first elements of a codeowners line. 
    Returns a dictionary of 'clean' codeowners lines."""
    codeowners_only = {}
    splat_line = False

    for key, value in codeowners_content.items():
        # Disregard empty line, comment, header, or a line filled with space
        if not value or check_if_comment_or_header(value) or value.isspace():
            invalid_syntax_line = 0
            continue

        invalid_syntax_line = key
        codeowners_only[key] = separate_line_codeowners(value)

        # There must be one line starting with '*'
        if not splat_line:
            splat_line = check_for_splat(codeowners_only[key][0])

        # Means there's either no codeowners in line or no repo/file/directory
        if len(codeowners_only[key]) < 2:
            break

        first_element = check_codeowner_regex(codeowners_only[key][0], get_regex('first_element_regex'))

        # First element is treated as repo/file/directory, remove it for regex check
        if not first_element:
            print(f'{branch}: Line {key}: First Element Skipped, Being Treated as a Repo/File/Directory. - "{codeowners_only[key][0]}"')
            codeowners_only[key] = codeowners_only[key][1:]
        # No repo/file/directory found
        else:
            break

        invalid_syntax_line = 0
    return codeowners_only, invalid_syntax_line, splat_line

def get_org_team(team, org):
    """Retrieve the contractors team object."""
    try:
        team = org.get_team_by_slug(team)
    except GithubException as error:
        if error.status == 404:
            print(f'{team} team not found in Org')
            return None
        print(f'Error retrieving {team} team: {error}')
        exit(1)
    return team

def get_valid_repo_teams(repo):
    """Returns team objects with write access in the repo 
    to check CODEOWNER team against."""
    repo_teams = []

    try: 
        teams = repo.get_teams()
        repo_teams = [team for team in teams if team.permission != 'pull' and team.permission != 'triage']
        for team in repo_teams:
            child_teams = team.get_teams()
            repo_teams.extend([team for team in child_teams])
    except GithubException as error:
        print(f'Error retrieving repository teams: {error}')
        exit(1)
    return repo_teams

def get_org_members(org):
    """Returns all members in an org."""
    try: 
        members = org.get_members()
    except GithubException as error:
        print(f'Error retrieving organization members: {error}')
        exit(1)
    return [(member.login).casefold() for member in members]

def get_team_members(team):
    """Retrieve all members of a team."""
    try:
        team_members = team.get_members()
    except GithubException as error:
        print(f'Error retrieving team members: {error}')
        exit(1)
    return [team_member.login for team_member in team_members]

def compare_team_members(team_members, contractors_team_members):
    """Return team members found in both team and contractors team."""
    return [member for member in team_members if member in contractors_team_members]

def get_username_from_email(email, org_members):
    """Returns username if it corresponds to an email found
    in CODEOWNERS file."""
    email_array = email.split('@')
    email_name = email_array[0].split('.')
    email_name = [name.lower() for name in email_name]

    for member in org_members:
        member_name = member.split('-')
        member_name = [name.lower() for name in member_name]
        # Delete 'sp' from end of username
        del member_name[-1]
        # Member name must be at least a first and last name (minus the -sp)
        if not member_name or len(member_name) < 2:
            continue

        for element in member_name:
            # Some usernames have a number appended due to duplicate names
            element = ''.join([x for x in element if not x.isdigit()])
        # Check first and last name
        if email_name[0] == member_name[0] and email_name[-1] == member_name[-1]:
            return f'@{member}'
    return None

def separate_into_org_team(codeowner):
    """Split 'org/team' and return separated collaborator."""
    codeowner_team_org = codeowner.split('/')
    return codeowner_team_org[0], codeowner_team_org[1]

def validate_team_codeowner(org, line, codeowner, repo_teams, contractors_team, contractor_members):
    """Ensures team is valid in a repo and contains no contractors."""
    # Separate org/team into org, team
    codeowner_org, codeowner = separate_into_org_team(codeowner)
    if not codeowner_org[1:] == org.login:
        return f'Line {line}: Invalid Org in CODEOWNERS File. - "{codeowner_org[1:]}"'

    # Need to grab the codeowner team object for member comparison
    codeowner_team = [team for team in repo_teams if team.slug == codeowner]
    if codeowner_team:
        codeowner_team_members = get_team_members(codeowner_team[0])
        # Prevents codeowners teams that are too large
        if len(codeowner_team_members) > 50:
            return f'Line {line}: Too many members in codeowners team: {codeowner}, members: {len(codeowner_team_members)}. Must be <= 50.'
        if contractors_team:
            # Ensure no contractor is in the codeowner team
            if compare_team_members(codeowner_team_members, contractor_members) or codeowner == contractors_team.slug:
                return f'Line {line}: Contractors Not Allowed to be in CODEOWNER file team or be the CODEOWNER team itself - Contractors: {contractor_members}.'
    else:
        return f'Line {line}: Codeowner in CODEOWNERS File does not have Repository Write Permissisons, is a contractors team, or does not exist in the {org.login} Org - "team: {codeowner}".'
    return f''

def validate_member_codeowner(line, codeowner, email, regex_result, org_members, contractor_members):
    """Ensures org member exists, is valid and not a contractor."""
    if not codeowner or codeowner[1:] not in org_members or codeowner[1:] in contractor_members:
        if email:
            codeowner = email
        return f'Line {line}: Codeowner in CODEOWNERS File does not have Repository Write Permissions or is/has an Unallowed Contractor. Please use username for automation accounts. - "{regex_result}: {codeowner}".'
    return f''

def determine_branch_fail(base_branch, compare_branch):
    base_branch['base_success'] = True
    compare_branch['compare_success'] = True

    if not base_branch['exists'] or not base_branch['valid_syntax']:
        base_branch['base_success'] = False
    if not compare_branch['exists'] or not compare_branch['valid_syntax']:
        compare_branch['compare_success'] = False
    return base_branch, compare_branch

def block_pr(base_branch, compare_branch):
    fail_message = f'Invalid or Missing CODEOWNERS File in both Base and Compare Branches. Cannot Merge.'
    base_fail_message = f'Invalid or Missing CODEOWNERS File in Base Branch. Cannot Merge. Add valid CODEOWNERS File to PR.'
    base_success_message = f'Valid CODEOWNERS File in Base Branch. Will be merged.'
    cannot_merge_message = f'Cannot Merge Invalid Compare Branch CODEOWNERS to Base Branch.'
    valid_merge_message = f'Valid Compare Branch CODEOWNERS will be Merged to Base Branch.'
    base_success = base_branch['base_success']
    compare_success = compare_branch['compare_success']

    print(f'{base_branch["name"]}: {base_branch["message"]}')
    print(f'{compare_branch["name"]}: {compare_branch["message"]}')

    # compare_branch['skip'] = No PR in compare branch, CODEOWNERS parsing skipped
    if not base_success and compare_branch['skip']:
        print(base_fail_message)
        exit(1)
    elif base_success and compare_branch['skip']:
        print(base_success_message)
        exit(0)
    elif not base_success and not compare_success:
        print(fail_message)
        exit(1)
    elif base_success and not compare_success:
        print(cannot_merge_message)
        exit(1)
    print(valid_merge_message)
    exit(0)


def main():
    token = sys.argv[1]
    pr_number = int(sys.argv[2])
    try: 
        github = Github(token)
        branches = {'base': os.getenv("GITHUB_BASE_REF"), 'compare': os.getenv("GITHUB_HEAD_REF")}
        org_repo = os.getenv("GITHUB_REPOSITORY").split('/')
        org = github.get_organization(os.getenv("GITHUB_REPOSITORY_OWNER"))
        repo = org.get_repo(org_repo[1])
    except GithubException as error:
        print(f'Error loading GitHub org or repo: {error}')
        exit(1)

    # Set up for job success/failure comparison and logging
    base_branch = {'name': branches['base'], 'exists': False, 'valid_syntax': False, 'message': ''}
    compare_branch = {'name': branches['compare'], 'exists': False, 'valid_syntax': False, 'skip': False, 'message': ''}

    # Check CODEOWENRS validity for both base and compare branches
    for key, value in branches.items(): 
        branch_dict = base_branch if key == 'base' else compare_branch
        # CODEOWNERS File not found in compare branch, only check base
        if key == 'compare' and not check_codeowners_file_pr(repo, pr_number):
            branch_dict['message'] = f'CODEOWNERS File not found in PR.'
            branch_dict['skip'] = True
            continue

        if key == 'base' and not check_for_codeowners_file_branch(repo):
            branch_dict['message'] = f'CODEOWNERS File does not Exist.'
            continue

        branch_dict['exists'] = True
        try:
            codeowners_content = repo.get_contents('CODEOWNERS', value).decoded_content.decode()
        except GithubException as error:
            print(f'Error loading repository CODEOWNERS content: {error}')
            exit(1)

        # Get dict of {'line_#': 'line'}
        codeowners_lines_dict = get_codeowner_lines_dict(codeowners_content)

        if not codeowners_lines_dict:
            branch_dict['message'] = f'CODEOWNERS File is Empty.'
            continue

        # Only includes codeowners (no files) with corresponding line number
        codeowners_only_dict, invalid_syntax_line, splat_line = get_codeowners_only(codeowners_lines_dict, branch_dict['name'])

        # One line must start with '*' for entire repo to be covered by CODEOWNERS
        if not splat_line:
            branch_dict['message'] = f'CODEOWNERS File Requires 1 Line starting with "*".'
            continue

        # A line has invalid syntax or dict empty
        if not codeowners_only_dict or invalid_syntax_line:
            # If invalid_syntax_line == False, then it must be line 1
            line = invalid_syntax_line if invalid_syntax_line else 1
            branch_dict['message'] = f'Line {line}: Line Syntax/Spelling Invalid or No Codeowners Found. - "{codeowners_lines_dict[line]}"'
            continue

        # Need org members for member comparison
        org_members = get_org_members(org)
        # Need the team objects for member comparison
        contractors_team = get_org_team('contractors', org)
        repo_teams = get_valid_repo_teams(repo)
        contractor_members = get_team_members(contractors_team) if contractors_team else []
        
        # Check each codeowner regex and elements line by line
        for line, value in codeowners_only_dict.items():
            # Check each codeowner in a line
            for codeowner in value:
                codeowner = codeowner.casefold()
                regex_result = check_codeowner_regex(codeowner, get_regex('codeowner_regex'))
                email = ''

                if not regex_result:
                    branch_dict['message'] = f'Line {line}: Codeowner Syntax or Spelling Incorrect in CODEOWNERS File. - "{codeowner}"'
                    break
                elif regex_result == 'team':
                    branch_dict['message'] = validate_team_codeowner(org, line, codeowner, repo_teams, contractors_team, contractor_members)
                    # Break on invalid team, continue to parse on valid team
                    if branch_dict['message']:
                        break
                    else:
                        continue
                elif regex_result == 'email':
                    # Save email for potential error message
                    email = codeowner
                    # Retrieve github member username using email for comparison
                    codeowner = get_username_from_email(codeowner, org_members)

                # Not a team, check for collaborator/member of org
                branch_dict['message'] = validate_member_codeowner(line, codeowner, email, regex_result, org_members, contractor_members)
                if branch_dict['message']:
                    break
            else:
                # All codeowners in a line are valid
                branch_dict['valid_syntax'] = True
                branch_dict['message'] = f'Codeowners in CODEOWNERS File are Valid.'
                continue
            # There is an invalid codeowner in a line
            branch_dict['valid_syntax'] = False
            break
   
    # Determine if pr should be blocked based on branch failures and log results
    base_branch, compare_branch = determine_branch_fail(base_branch, compare_branch)
    return block_pr(base_branch, compare_branch)

if __name__ == "__main__":
    main()