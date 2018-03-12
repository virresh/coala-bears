import re
import shutil
import os

from urllib.parse import urlparse
from coala_utils.ContextManagers import change_directory
from coalib.misc.Shell import run_shell_command
from coalib.results.Result import Result
from bears.vcs.CommitBear import _CommitBear
from coalib.settings.FunctionMetadata import FunctionMetadata


class HgCommitBear(_CommitBear):
    LANGUAGES = {'Hg'}
    SUPPORTED_HOST_KEYWORD_REGEX = {
        'bitbucket': (r'[Cc]los(?:e[sd]?|ing)'
                      r'|[Rr]esolv(?:e[sd]?|ing)'
                      r'|[Ff]ix(?:e[sd]|ing)?')
    }

    @classmethod
    def get_shortlog_checks_metadata(cls):
        return FunctionMetadata.from_function(
            cls.check_shortlog,
            omit={'self', 'shortlog'})

    @classmethod
    def get_body_checks_metadata(cls):
        return FunctionMetadata.from_function(
            cls.check_body,
            omit={'self', 'body'})

    @classmethod
    def get_issue_checks_metadata(cls):
        return FunctionMetadata.from_function(
            cls.check_issue_reference,
            omit={'self', 'body'})

    @classmethod
    def get_metadata(cls):
        return FunctionMetadata.merge(
            FunctionMetadata.from_function(
                cls.run,
                omit={'self', 'dependency_results'}),
            cls.get_shortlog_checks_metadata(),
            cls.get_body_checks_metadata(),
            cls.get_issue_checks_metadata())

    @classmethod
    def check_prerequisites(cls):
        if shutil.which('hg') is None:
            return 'hg is not installed.'
        else:
            return True

    @staticmethod
    def get_host_from_remotes():
        """
        Retrieve the first host from the list of mercurial remotes.
        """
        remotes, _ = run_shell_command('hg paths')

        remotes = [url.split()[-1] for url in remotes.splitlines()]
        if len(remotes) == 0:
            return None

        url = remotes[0]
        if 'hg@' in url:
            netloc = re.findall(r'@(\S+)\.', url)[0]
        else:
            netloc = urlparse(url)[1]
        return netloc.split('.')[0].split('@')[-1]

    def run(self, allow_empty_commit_message: bool = False, **kwargs):
        """
        Check the current mercurial commit message at HEAD.

        This bear ensures automatically that the shortlog and body do not
        exceed a given line-length and that a newline lies between them.

        :param allow_empty_commit_message: Whether empty commit messages are
                                           allowed or not.
        """
        with change_directory(self.get_config_dir() or os.getcwd()):
            stdout, stderr = run_shell_command(
                'hg log -l 1 --template "{desc}"')

        if stderr:
            self.err('hg:', repr(stderr))
            return

        stdout = stdout.rstrip('\n')
        pos = stdout.find('\n')
        shortlog = stdout[:pos] if pos != -1 else stdout
        body = stdout[pos+1:] if pos != -1 else ''

        if len(stdout) == 0:
            if not allow_empty_commit_message:
                yield Result(self, 'HEAD commit has no message.')
            return

        yield from self.check_shortlog(
            shortlog,
            **self.get_shortlog_checks_metadata().filter_parameters(kwargs))
        yield from self.check_body(
            body,
            **self.get_body_checks_metadata().filter_parameters(kwargs))
        yield from self.check_issue_reference(
            body,
            **self.get_issue_checks_metadata().filter_parameters(kwargs))

    def check_issue_reference(self, body,
                              body_close_issue: bool=False,
                              body_close_issue_full_url: bool=False,
                              body_close_issue_on_last_line: bool=False,
                              body_enforce_issue_reference: bool=False):
        """
        Check for matching issue related references and URLs.

        :param body:
            Body of the commit message of HEAD.
        :param body_close_issue:
            BitBucket support auto closing issues with
            commit messages. When enabled, this checks for matching keywords
            in the commit body by retrieving host information from mercurial
            configuration. By default, if none of ``body_close_issue_full_url``
            and ``body_close_issue_on_last_line`` are enabled, this checks for
            presence of short references like ``closes #213``.
            Otherwise behaves according to other chosen flags.
            More on keywords follows.
            [BitBucket](https://confluence.atlassian.com/bitbucket/resolve-issues-
            automatically-when-users-push-code-221451126.html)
        :param body_close_issue_full_url:
            Checks the presence of issue close reference with a full URL
            related to some issue. Works along with ``body_close_issue``.
        :param body_close_issue_on_last_line:
            When enabled, checks for issue close reference presence on the
            last line of the commit body. Works along with
            ``body_close_issue``.
        :param body_enforce_issue_reference:
            Whether to enforce presence of issue reference in the body of
            commit message.
        """
        if not body_close_issue:
            return

        host = self.get_host_from_remotes()

        if host is None:
            yield Result(self, 'No host configured in path.')
            return
        if host not in self.SUPPORTED_HOST_KEYWORD_REGEX:
            yield Result(self, 'Un-supported host in path.')
            return

        if body_close_issue_on_last_line:
            if body:
                body = body.splitlines()[-1]
            result_message = ('Body of HEAD commit does not contain any {} '
                              'reference in the last line.')
        else:
            result_message = ('Body of HEAD commit does not contain any {} '
                              'reference.')

        if body_close_issue_full_url:
            result_info = 'full issue'
            issue_ref_regex = (
                r'https?://{}\S+/issues/(\S+)/\S+'.format(re.escape(host)))
        else:
            result_info = 'issue'
            issue_ref_regex = r'(?:\w+/\w+)?#(\S+)/?'

        concat_regex = '|'.join(kw for kw in self.CONCATENATION_KEYWORDS)
        compiled_joint_regex = re.compile(
            r'(?:{0})\s+'           # match issue related keywords,
                                    # eg: fix, closes etc.

            r'((?:\S(?!{1}))*\S'    # match links/tags
                                    # eg: fix #123, fix https://bitbucket.com

            r'(?:\s*(?:{1})\s*'     # match conjunctions like ',','and'

            r'(?!{0})'              # reject if new keywords appear

            r'(?:\S(?!{1}))*\S)*)'  # match links/tags followed after
                                    # conjunctions if any
            r''.format(
                self.SUPPORTED_HOST_KEYWORD_REGEX[host],
                concat_regex))

        matches = compiled_joint_regex.findall(body)

        if body_enforce_issue_reference and len(matches) == 0:
            yield Result(self, result_message.format(result_info))
            return

        compiled_issue_ref_regex = re.compile(issue_ref_regex)
        compiled_issue_no_regex = re.compile(r'[1-9][0-9]*')
        compiled_concat_regex = re.compile(
            r'\s*(?:{})\s*'.format(concat_regex))

        for match in matches:
            for issue in re.split(compiled_concat_regex, match):
                reference = compiled_issue_ref_regex.fullmatch(issue)
                if not reference:
                    yield Result(self, 'Invalid {} reference: '
                                       '{}'.format(result_info, issue))
                elif not compiled_issue_no_regex.fullmatch(reference.group(1)):
                    yield Result(self, 'Invalid issue number: '
                                       '{}'.format(issue))
