# Licensed under the Apache License: http://www.apache.org/licenses/LICENSE-2.0
# For details: https://bitbucket.org/ned/coveragepy/src/default/NOTICE.txt

"""Source file annotation for coverage.py."""

import io
import os
import re

from coverage import files

from coverage.files import flat_rootname
from coverage.misc import isolate_module
from coverage.report import Reporter

os = isolate_module(os)


class AnnotateReporter(Reporter):
    """Generate annotated source files showing line coverage.

    This reporter creates annotated copies of the measured source files. Each
    .py file is copied as a .py,cover file, with a left-hand margin annotating
    each line::

        > def h(x):
        -     if 0:   #pragma: no cover
        -         pass
        >     if x == 1:
        !         a = 1
        >     else:
        >         a = 2

        > h(2)

    Executed lines use '>', lines not executed use '!', lines excluded from
    consideration use '-'.

    """

    def __init__(self, coverage, config, lcov_file=None):
        super(AnnotateReporter, self).__init__(coverage, config)
        self.directory = None

    blank_re = re.compile(r"\s*(#|$)")
    else_re = re.compile(r"\s*else\s*:\s*(#|$)")

    def report(self, morfs, directory=None, lcov_file=None):
        """Run the report.

        See `coverage.report()` for arguments.

        """
        self.report_files(self.annotate_file, morfs, directory,
                          lcov_file=lcov_file)

    def print_ba_lines(self, lcov_file, analysis):
      # This function takes advantage of the fact that the functions
      # in Analysis returns arcs in sorted order of their line numbers
      # and mark the branch numbers in the same order of the
      # destination line numbers of the arcs. For example:
      #
      # Line
      # 10    if (something):
      # 11      do_something
      # 12    else:
      # 13      do_something_else
      #
      # In the coverage analysis result, the tool returns arc list [
      # ... (10,11), (10, 13) ...].  We will then regard (10,11) as
      # the first branch at line 10 and (10, 13) as the second branch
      # at line 10. This is important as in lcov file the branch
      # coverage info must appear in order, e.g., suppose the test
      # code executes the 'if' branch, the results in lcov format will
      # be
      #
      #  BA: 10, 2  (the first branch is taken)
      #  BA: 10, 1  (the second branch is executed but not taken)
      #
      # Note that in other languages the branch ordering might be
      # treated differently.

      all_arcs = analysis.arc_possibilities()
      branch_lines = set(analysis.branch_lines())
      missing_branch_arcs = analysis.missing_branch_arcs()
      missing = analysis.missing

      for source_line,target_line in all_arcs:
        if source_line in branch_lines:
          if source_line in missing:
            # Not executed
            lcov_file.write('BA:%d,0\n' % source_line)
          else:
            if (source_line in missing_branch_arcs) and (
                target_line in missing_branch_arcs[source_line]):
              # Executed and not taken
              lcov_file.write('BA:%d,1\n' % source_line)
            else:
              # Executed and taken
              lcov_file.write('BA:%d,2\n' % source_line)

    (MISSED, COVERED, BLANK, EXCLUDED) = ('!', '>', ' ', '-')
    def annotate_file(self, fr, analysis, lcov_file=None):
        """Annotate a single file.

        `fr` is the FileReporter for the file to annotate.

        """
        reverse_mapping = files.get_filename_from_cf(fr.filename)

        filename = fr.filename
        if reverse_mapping:
            filename = reverse_mapping

        statements = sorted(analysis.statements)
        missing = sorted(analysis.missing)
        excluded = sorted(analysis.excluded)

        if lcov_file:
            lcov_file.write("SF:%s\n" % filename)

        if self.directory:
            dest_file = os.path.join(self.directory, flat_rootname(fr.relative_filename()))
            if dest_file.endswith("_py"):
                dest_file = dest_file[:-3] + ".py"
            dest_file += ",cover"
        else:
            dest_file = fr.filename + ",cover"

        if not lcov_file:
            dest = io.open(dest_file, 'w', encoding='utf8')

        if True:  # GOOGLE: force indent for easy comparison; original:
                  # with io.open(dest_file, 'w', encoding='utf8') as dest:
            i = 0
            j = 0
            covered = True
            source = fr.source()
            for lineno, line in enumerate(source.splitlines(True), start=1):
                while i < len(statements) and statements[i] < lineno:
                    i += 1
                while j < len(missing) and missing[j] < lineno:
                    j += 1
                if i < len(statements) and statements[i] == lineno:
                    covered = j >= len(missing) or missing[j] > lineno
                if self.blank_re.match(line):
                    line_type = self.BLANK
                elif self.else_re.match(line):
                    # Special logic for lines containing only 'else:'.
                    if i >= len(statements) and j >= len(missing):
                        line_type = self.MISSED
                    elif i >= len(statements) or j >= len(missing):
                        line_type = self.COVERED
                    elif statements[i] == missing[j]:
                        line_type = self.MISSED
                    else:
                        line_type = self.COVERED
                elif lineno in excluded:
                    line_type = self.EXCLUDED
                elif covered:
                    line_type = self.COVERED
                else:
                    line_type = self.MISSED

                if not lcov_file:
                    dest.write("%s %s" % (line_type, line))
                else:
                    # Omit BLANK & EXCLUDED line types from this lcov output type.
                    if line_type == self.COVERED:
                        lcov_file.write("DA:%d,1\n" % lineno)
                    elif line_type == self.MISSED:
                      lcov_file.write("DA:%d,0\n" % lineno)
        # Write branch coverage results
        if lcov_file and analysis.has_arcs():
            self.print_ba_lines(lcov_file, analysis)
        if lcov_file:
            lcov_file.write("end_of_record\n")
        else:
            dest.close()  # XXX try: finally: more "appropriate" than "if True"
