import requests
import time
import json
import re
import argparse
import sys

GRAPHQL_URL = "https://api.github.com/graphql"
GITHUB_BASE_URL = "https://github.com/"
API_URL = "https://api.github.com"

# Checks a given string to see if it is formatted like the HTLM URL of a GitHub issue
# pattern: https://github.com/<owner>/<repo>/issues/<issue number>
#   input: url- the HTML URL to check
# returns:
#      True- if the URL is formatted like an issue url
#     False- if the URL isn not formatted like an issue url
#
def is_github_issue_url(url):
    if url is None or not isinstance(url, str) or not url.strip().startswith(GITHUB_BASE_URL):
        return False
    issue_url = url.strip()[len(GITHUB_BASE_URL):]
    parts = issue_url.split('/')
    if len(parts) >= 4 and parts[2] == "issues":
        return True
    return False    

# Extract task issue URLs from the issue body
def extract_tasks(issue_body):
    tasks = []
    lines = issue_body.split('\n')
    for line in lines:
        if line.strip().startswith("- [ ]") or line.strip().startswith("- [x]"):
            task_text = line[5:]
            task_checked = False
            if line.strip()[3] == 'x':
                task_checked = True
            task_info = {'text': task_text.strip(), 'is_checked': task_checked}
            tasks.append(task_info)

    return tasks

# splits a standard formatted GitHub issue url into owner (org or user), repo and issue_id
# where a url looks like https://github.com/<owner>/<repo>/issues/<issue_id>
#  input: a GitHub issue url
# output: a dict with owner, repo and issue_id attributes, all as strings e.g.:
#         {
#            'owner': 'someorg',
#            'repo': 'myrepo',
#            'issue_id': "17"
#         }
#         or an exception if an error occurs with a message describing the error
def split_github_issue_url(issue_url):
    # Remove the base URL part
    if issue_url.startswith(GITHUB_BASE_URL):
        issue_url = issue_url[len(GITHUB_BASE_URL):]
    else:
        raise ValueError("GitHub issue URL must start with https://github.com/")

    # Split the remaining part by '/'
    parts = issue_url.split('/')
    if len(parts) >= 4 and parts[2] == "issues":
        owner = parts[0]
        repo = parts[1]
        issue_id = parts[3]
        return {'owner':owner, 'repo':repo, 'issue_id':issue_id}
    else:
        raise ValueError(f"Invalid GitHub issue URL: {issue_url}")

# splits a standard formatted GitHub issue url into owner (org or user) and repo
# where a repo url looks like https://github.com/<owner>/repo
#  input: a GitHub issue url
# output: a dict with owner, repo and issue_id attributes, all as strings e.g.:
#         {
#            'owner': 'someorg',
#            'repo': 'myrepo'
#         }
#         or an exception if an error occurs with a message describing the error
def split_github_repo_url(repo_url):
    # Remove the base URL part
    if repo_url.startswith(GITHUB_BASE_URL):
        repo_url = repo_url[len(GITHUB_BASE_URL):]
    else:
        raise ValueError("GitHub repo URL must start with https://github.com/")
    
    # Split the remaining part by '/'
    parts = repo_url.split('/')
    if len(parts) == 2:
        owner = parts[0]
        repo = parts[1]    
        return {'owner':owner, 'repo':repo}
    else:
        raise ValueError(f"Invalid GitHub repo URL: {repo_url}")

#create an issue body tasklist section given a list of tasks
def create_tasklist_body(tasks):
    if tasks is None or len(tasks) == 0:
        return('')
    
    task_body = "```[tasklist]\n### Tasks"
    for task in tasks:
        brackets = '[ ]'
        if task['is_checked']:
            brackets = '[x]'
        task_line = f"\n- {brackets} {task['text']}"
        task_body = task_body + task_line
    task_body = task_body + "\n```"
    return(task_body)

#given a GitHub issue body remove the task list from it and optionally replace with a new one, 
#if replacement_tasklist is supplied
def replace_tasklist_in_issue_body(issue_body, replacement_tasklist = ''):
    # Regular expression pattern to match task lists with start and end parts
    tasklist_pattern = r'``` *\[tasklist\](.|\n)*?```'
    # Replace task lists with an empty string
    updated_body = re.sub(tasklist_pattern, replacement_tasklist, issue_body, 1)
    
    return updated_body


class Tasks2Subissues:
    def __init__(self, token, parent_issue_url, ref_repo_url = None):
        self.parent_issue_url = parent_issue_url
        self.reference_repo = None
        self.reference_repo_owner = None
        if not ref_repo_url is None:
            try:
                ref_repo_parts = split_github_repo_url(ref_repo_url)
                self.reference_repo = ref_repo_parts['repo']
                self.reference_repo_owner = ref_repo_parts['owner']
            except ValueError as e:
                print(f"[ERROR: {e}")
                exit(1)             
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json"
        }

    #create a GitHub issue under given owner and repo with the
    #given title, description (body) and state.  The state is set after
    #the issue is created because state isn't an attribute available at create time
    # inputs:
    #        owner- issue owner, organization or user
    #         repo- issue repository
    #        title- title of issue
    #  description- the body of the issue
    #        state- (optional) the state of the issue, open or closed, defaults to open
    # returns: HTML URL of the new issue, on success
    #          An Exception with a description of the error, if an error occurs 
    def create_issue(self, owner, repo, title, description, state='open'):
        # GitHub API URL to create an issue
        url = f'https://api.github.com/repos/{owner}/{repo}/issues'
        
        # Data for the new issue
        data = {
            'title': title,
            'body': description
        }
        
        # Make the HTTP POST request to create the issue
        response = requests.post(url, headers=self.headers, data=json.dumps(data))
        # Check the response
        if response.status_code == 201:
            issue_url = response.json().get('html_url')
            if state == 'closed':
                url = f"{url}/{response.json().get('number')}"
                requests.patch(url, headers=self.headers, json={"state":"closed"})
            return issue_url
        else:
            raise Exception(f"issue POST failed, can't create issue in {url}, {response.status_code}, {response.content}")



    # create a new issue in "reference" repo, with a link to an
    # issue in a GitHub org/user other than the parent issue that
    # is being restructured (sub-issues must be part of the same GitHub org/user).
    #
    # the title of the referenced issue will be used for the new issue with
    # the org/user and repo prefixed
    #
    # The description of the new issue will be created with a link to the
    # referenced issue
    #
    # input: issue_url- the GitHub URL to the issue that will be referenced
    # ouput: the url of the new issue
    #        an exception if an error occurs with a message describing the error
    def create_reference_issue(self, issue_url):
        #make a call to GitHub to get some details about the issue to be referenced
        #check to make sure we get back the fields that we need
        issue_details = self.fetch_issue_details_by_url(issue_url)
        if not 'title' in issue_details:
            raise Exception("title field not present")
        if not 'state' in issue_details:
            raise Exception("state field not present")
        
        #get the owner and repo of the issue to be referenced
        #split_github_issue_url will raise exceptions if there are any problems with the url
        issue_parts = split_github_issue_url(issue_url)
        
        new_issue_title = f"{issue_parts['owner']}/{issue_parts['repo']}#{issue_parts['issue_id']}:{issue_details['title']}"
        new_issue_description = f"This issue is a reference/placeholder to: [{new_issue_title}]({issue_url})"
        reference_repo_url = self.create_issue(self.reference_repo_owner, self.reference_repo, new_issue_title, new_issue_description, issue_details['state'])
        return reference_repo_url


    # given an issue html url, gets the information available from the standard REST GET
    #   input:  issue_url- the html url of the issue
    # returns: The dict of the converted json from the standard RESTful GET of the issue
    def fetch_issue_details_by_url(self, issue_url):
        issue_parts = split_github_issue_url(issue_url)
        return(self.fetch_issue_details(issue_parts['owner'], issue_parts['repo'], issue_parts['issue_id']))
        
    # given an issue's owner, repo and issue number, gets the information available from the standard
    # RESTful GET
    # inputs:
    #          owner- issue owner, organization or user
    #           repo- issue repository
    #   issue_number- the issue number (within the repo, not the nod id)
    # returns: The dict of the converted json from the standard RESTful GET of the issue
    # Fetch the task list from the parent issue
    def fetch_issue_details(self, owner, repo, issue_number):
        url = f"https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}"
        response = requests.get(url, headers=self.headers)
        issue_data = response.json()
        return issue_data

    # Convert issue HTML URL to issue node ID using the REST API
    #
    #   input: The HTML URL of the issue
    # returns: The node id of the issue
    def fetch_issue_node_id(self,issue_url):
        issue_parts = split_github_issue_url(issue_url)
        issue_data = self.fetch_issue_details(issue_parts['owner'], issue_parts['repo'], issue_parts['issue_id'])
        return issue_data["node_id"]
    
    # link an issue as a sub-issue, given the node ids of the parent and child (sub) issues
    #  inputs:
    #     parent_issue_id- the node id (not repo number) of the parent issue
    #      child_issue_id- the node id (not repo number) of the child/sub issue
    #
    # returns: True if the issues were linked
    #          otherwise an Exception if an error occurred with the description of the error
    def link_parent_issue_and_sub_issue(self,parent_issue_id, child_issue_id):
        query = """
        mutation AddSubIssue($parentIssueId: ID!, $subIssueId: ID!) {
          addSubIssue(input: {issueId: $parentIssueId, subIssueId: $subIssueId}) {
            issue {
              id
              subIssues(first:10) {
                totalCount
                nodes {
                  id
                  title
                }
              }
            }
            subIssue {
              id
              title
              url
            }
          }
        }
        """
        variables = {
            'parentIssueId': parent_issue_id,
            'subIssueId': child_issue_id
        }
        
    
        response = requests.post(
            GRAPHQL_URL,
            headers=self.headers,
            json={"query": query, "variables": variables})
        rval = response.json()
        if 'errors' in rval and len(rval['errors']) > 0:
            err_resp = ''
            mesg_div = ''
            first = True
            for err in rval['errors']:
                if 'message' in err:
                    err_resp = err_resp + mesg_div + err['message']
                    if first:
                        mesg_div = " | "
                        first = False
            raise Exception("Unable to link sub-issue:" + err_resp)
    
        return True

    #Reads the tasklist of an issue, breaks the tasks into three groups
    #  - issues to add as sub-issues- github issue urls under same org/user as parent 
    #  - issues to create a reference issue- github issue urls under different org/user as parent
    #  - non-issues- anything else
    #
    #  Then creates reference issues for those under a different org/user and adds all as sub-issues
    #  to the parent.
    #
    #  input: url of the parent issue
    # output: Nothing returned, prints the status of what was done to stdout
    def create_sub_issues(self):        
        #keep track of how many errors we encounter along the way
        error_count = 0
        
        #get the info for the parent issue
        try:
            parent_issue_info = split_github_issue_url(self.parent_issue_url)
            parent_owner = parent_issue_info['owner']
            parent_repo = parent_issue_info['repo']
            parent_issue_num = parent_issue_info['issue_id']
            issue_data = self.fetch_issue_details(parent_owner, parent_repo, parent_issue_num)
            parent_body = issue_data["body"]
            tasks = extract_tasks(parent_body)
            parent_issue_id = self.fetch_issue_node_id(issue_data["html_url"])
            print(f"Converting tasklist issues to sub-issues for {self.parent_issue_url}")
        except Exception as e:
            print(f"[ERROR]: Unable to get issue information for parent issue: {self.parent_issue_url}: {e}")
            exit(1)
    
        #create lists of 1-issues with same owners, 2-issues with different owners and 3-non-issues
        same_owner_urls = []
        different_owner_urls = []
        non_issue_tasks = []
        for task in tasks:
            try:
                task_description = task['text']
                if is_github_issue_url(task_description):
                    sub_info = split_github_issue_url(task_description)
                    if parent_owner == sub_info['owner']:
                        same_owner_urls.append(task_description)
                    else:
                        different_owner_urls.append(task_description)
                else:
                    non_issue_tasks.append(task)
            except Exception as e:
                error_count = error_count + 1
                print(f"[ERROR]: Error encountered while categorizing task {task}: {e}")
    
        if len(different_owner_urls) > 0 and (self.reference_repo is None or self.reference_repo_owner is None):
            print(f'[ERROR]: There are {len(different_owner_urls)} issues to convert from a different owner than the target issue. Must provide a "reference repo url" via --refrepo option to create reference issues in.')
            exit(1)

        #create reference issues in the parent owner's GitHub org/user for the issues that are under a different owner
        #add the new reference issues to the list of urls that will be linked as sub-issues
        for iss_url in different_owner_urls:
            try:
                ref_url = self.create_reference_issue(iss_url)
                same_owner_urls.append(ref_url)
                print(f"Created a reference issue for: {iss_url}, reference issue: {ref_url}")
            except Exception as e:
                error_count = error_count + 1
                print(f"[ERROR]: Error encountered while creating a reference issue for {iss_url}: {e}")
    
    
        #link tasks as sub-issues on parent
        for iss_url in same_owner_urls:
            try:
                sub_issue_id = self.fetch_issue_node_id(iss_url)
                self.link_parent_issue_and_sub_issue(parent_issue_id, sub_issue_id)
                print(f"Linked issue as sub-issue: {iss_url}")
                #sleep for 5 seconds between linking sub-issues.  GitHub complains if
                #we send too many quickly
                time.sleep(5)
            except Exception as e:
                error_count = error_count + 1
                print(f"[ERROR]: Error encountered while linking issue as sub-issue {iss_url}: {e}")
                    
    
        #replace (or delete) the tasklist in the parent_issue body with remaining tasks that
        #weren't issue urls
        #don't do anything if no issues were connected as sub-issues
        #if there were errors above, don't replace the tasklist
        if error_count > 0:
            errmsg = "errors were"
            if error_count == 1:
                errmsg = "error was" 
            print(f"{error_count} {errmsg} found.  Will leave the task list as is on {self.parent_issue_url}")
            exit(1)
        try:

            if len(same_owner_urls) > 0:
                tasklist_body_part = ''
                tasklist_action = 'removed'
                #if no tasks remain to keep track of, just remove the whole task list
                #Only modify/delete tasklist if no errors were encountered above, so we don't lose track
                #of any tasks that weren't converted
                if error_count == 0 and len(non_issue_tasks) > 0:
                    tasklist_body_part = create_tasklist_body(non_issue_tasks)
                    tasklist_action = 'updated'
                new_body = replace_tasklist_in_issue_body(parent_body, tasklist_body_part)
                url = f"https://api.github.com/repos/{parent_owner}/{parent_repo}/issues/{parent_issue_num}"
                response = requests.patch(url, headers=self.headers, json={"body":new_body})
                if response.status_code != 200:
                    print(f"[ERROR]: Couldn't update tasklist body on parent {self.parent_issue_url} response_code:{response.status_code} response_message: {response.content}")
                else:
                    print(f"Tasklist {tasklist_action} on {self.parent_issue_url}")
            else:
                print(f"No tasks issues were converted to sub-issues on {self.parent_issue_url}")
            exit(0)
        except Exception as e:
            print(f"[ERROR]: Something happened while replacing tasklist body on parent {self.parent_issue_url} {e}")

# Main function to convert tasks to sub-issues
def main():
    parser = argparse.ArgumentParser(description="Convert GitHub tasklist issues to to sub-issues")
    parser.add_argument("--token", required=True, help="GitHub Personal access token")
    parser.add_argument("--issueurl", required=True, help="HTML URL of the tartet issue containing task list to the task list that will be converted")
    parser.add_argument("--refrepo", required=False, help="HTML URL of a repo where reference issues will be created. Only needed if the target issue contains task issues froma different owner.") 
    args = parser.parse_args()

    t2s = Tasks2Subissues(args.token, args.issueurl, args.refrepo)
    t2s.create_sub_issues()


if __name__ == "__main__": 
    main()