# tasks2subissues

A script to convert issue task lists to subissues

The python script contained here will convert any GitHub issues referenced in a task list within the body of a GitHub issue into linked sub-isses on the same target issue.  Given the url of a GitHub issue the script will:
  - parse a task list from the body of the issue into a list of issues to link as sub-issues
  - create reference issues in a supplied "reference repo" for any task issues that aren't under the same owner (org or user) as the target issue.  These issues will be linked as sub-issues instead.
  - link all of the task issues (or references of these issues) to the target issue as sub-issues
  - rewrite the task list section in the target issue removing any tasks that were converted to sub-issues. Any tasks that were non-issues will remain.  If all tasks were issues then the task list is removed. If there are any failures along the way converting issues, the task list isn't rewitten so no needed issue information is lost.

usage: `tasks2subissues.py [-h] --token TOKEN --issueurl ISSUEURL [--refrepo REFREPO]`

```
options:
  -h, --help           show this help message and exit
  --token TOKEN        GitHub Personal access token
  --issueurl ISSUEURL  HTML URL of the tartet issue containing task list to
                       the task list that will be converted
  --refrepo REFREPO    (optional) HTML URL of a repo where reference issues
                       will be created. Only needed if the target issue
		       contains task issues froma different owner.
```
Before running, make sure the libraries in requirements.txt are imported into your python environment.

Example usage: `python tasks2subissues --token <mygithubtoken> --issueurl https://github.com/myuserororg/myrepo/issues/42`
  
