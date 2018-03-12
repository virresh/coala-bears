import nltk
import re
import abc

from coalib.bears.GlobalBear import GlobalBear
from dependency_management.requirements.PipRequirement import PipRequirement
from coalib.results.Result import Result
from coalib.settings.Setting import typed_list


class _CommitBear(GlobalBear):
    __metaclass__ = abc.ABCMeta
    REQUIREMENTS = {PipRequirement('nltk', '3.2')}
    AUTHORS = {'The coala developers'}
    AUTHORS_EMAILS = {'coala-devel@googlegroups.com'}
    LICENSE = 'AGPL-3.0'
    CONCATENATION_KEYWORDS = [r',', r'\sand\s']

    _nltk_data_downloaded = False

    def setup_dependencies(self):
        if not self._nltk_data_downloaded and bool(
                self.section.get('shortlog_imperative_check', True)):
            nltk.download([
                'punkt',
                'averaged_perceptron_tagger',
            ])
            type(self)._nltk_data_downloaded = True

    def check_shortlog(self, shortlog,
                       shortlog_length: int=50,
                       shortlog_regex: str='',
                       shortlog_trailing_period: bool=None,
                       shortlog_imperative_check: bool=True,
                       shortlog_wip_check: bool=True):
        """
        Checks the given shortlog.

        :param shortlog:                 The shortlog message string.
        :param shortlog_length:          The maximum length of the shortlog.
                                         The newline character at end does not
                                         count to the length.
        :param shortlog_regex:           A regex to check the shortlog with.
        :param shortlog_trailing_period: Whether a dot shall be enforced at end
                                         end or not (or ``None`` for "don't
                                         care").
        :param shortlog_wip_check:       Whether a "WIP" in the shortlog text
                                         should yield a result or not.
        """
        diff = len(shortlog) - shortlog_length
        if diff > 0:
            yield Result(self,
                         'Shortlog of the HEAD commit contains {} '
                         'character(s). This is {} character(s) longer than '
                         'the limit ({} > {}).'.format(
                              len(shortlog), diff,
                              len(shortlog), shortlog_length))

        if (shortlog[-1] != '.') == shortlog_trailing_period:
            yield Result(self,
                         'Shortlog of HEAD commit contains no period at end.'
                         if shortlog_trailing_period else
                         'Shortlog of HEAD commit contains a period at end.')

        if shortlog_regex:
            match = re.fullmatch(shortlog_regex, shortlog)
            if not match:
                yield Result(
                    self,
                    'Shortlog of HEAD commit does not match given regex:'
                    ' {regex}'.format(regex=shortlog_regex))

        if shortlog_imperative_check:
            colon_pos = shortlog.find(':')
            shortlog = (shortlog[colon_pos + 1:]
                        if colon_pos != -1
                        else shortlog)
            has_flaws = self.check_imperative(shortlog)
            if has_flaws:
                bad_word = has_flaws[0]
                yield Result(self,
                             "Shortlog of HEAD commit isn't in imperative "
                             "mood! Bad words are '{}'".format(bad_word))
        if shortlog_wip_check:
            if 'wip' in shortlog.lower()[:4]:
                yield Result(
                    self,
                    'This commit seems to be marked as work in progress and '
                    'should not be used in production. Treat carefully.')

    def check_imperative(self, paragraph):
        """
        Check the given sentence/s for Imperatives.

        :param paragraph:
            The input paragraph to be tested.
        :return:
            A list of tuples having 2 elements (invalid word, parts of speech)
            or an empty list if no invalid words are found.
        """
        words = nltk.word_tokenize(nltk.sent_tokenize(paragraph)[0])
        # VBZ : Verb, 3rd person singular present, like 'adds', 'writes'
        #       etc
        # VBD : Verb, Past tense , like 'added', 'wrote' etc
        # VBG : Verb, Present participle, like 'adding', 'writing'
        word, tag = nltk.pos_tag(['I'] + words)[1:2][0]
        if(tag.startswith('VBZ') or
           tag.startswith('VBD') or
           tag.startswith('VBG') or
           word.endswith('ing')):  # Handle special case for VBG
            return (word, tag)
        else:
            return None

    def check_body(self, body,
                   body_line_length: int=72,
                   force_body: bool=False,
                   ignore_length_regex: typed_list(str)=(),
                   body_regex: str=None):
        """
        Checks the given commit body.

        :param body:                The body of the commit message of HEAD.
        :param body_line_length:    The maximum line-length of the body. The
                                    newline character at each line end does not
                                    count to the length.
        :param force_body:          Whether a body shall exist or not.
        :param ignore_length_regex: Lines matching each of the regular
                                    expressions in this list will be ignored.
        :param body_regex:          If provided, checks the presence of regex
                                    in the commit body.
        """
        if len(body) == 0:
            if force_body:
                yield Result(self, 'No commit message body at HEAD.')
            return

        if body[0] != '\n':
            yield Result(self, 'No newline found between shortlog and body at '
                               'HEAD commit. Please add one.')
            return

        if body_regex and not re.fullmatch(body_regex, body.strip()):
            yield Result(self, 'No match found in commit message for the '
                               'regular expression provided: %s' % body_regex)

        body = body.splitlines()
        ignore_regexes = [re.compile(regex) for regex in ignore_length_regex]
        if any((len(line) > body_line_length and
                not any(regex.search(line) for regex in ignore_regexes))
               for line in body[1:]):
            yield Result(self, 'Body of HEAD commit contains too long lines. '
                               'Commit body lines should not exceed {} '
                               'characters.'.format(body_line_length))
