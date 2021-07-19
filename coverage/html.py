# Licensed under the Apache License: http://www.apache.org/licenses/LICENSE-2.0
# For details: https://github.com/nedbat/coveragepy/blob/master/NOTICE.txt

"""HTML reporting for coverage.py."""

import datetime
import json
import os
import re
import shutil
import types

import coverage
from coverage.data import add_data_to_hash
from coverage.exceptions import CoverageException
from coverage.files import flat_rootname
from coverage.misc import ensure_dir, file_be_gone, Hasher, isolate_module, format_local_datetime
from coverage.report import get_analysis_to_report
from coverage.results import Numbers
from coverage.templite import Templite

os = isolate_module(os)


# Static files are looked for in a list of places.
STATIC_PATH = [
    # The place Debian puts system Javascript libraries.
    "/usr/share/javascript",

    # Our htmlfiles directory.
    os.path.join(os.path.dirname(__file__), "htmlfiles"),
]


def data_filename(fname, pkgdir=""):
    """Return the path to a data file of ours.

    The file is searched for on `STATIC_PATH`, and the first place it's found,
    is returned.

    Each directory in `STATIC_PATH` is searched as-is, and also, if `pkgdir`
    is provided, at that sub-directory.

    """
    tried = []
    for static_dir in STATIC_PATH:
        static_filename = os.path.join(static_dir, fname)
        if os.path.exists(static_filename):
            return static_filename
        else:
            tried.append(static_filename)
        if pkgdir:
            static_filename = os.path.join(static_dir, pkgdir, fname)
            if os.path.exists(static_filename):
                return static_filename
            else:
                tried.append(static_filename)
    raise CoverageException(
        f"Couldn't find static file {fname!r} from {os.getcwd()!r}, tried: {tried!r}"
    )


def read_data(fname):
    """Return the contents of a data file of ours."""
    with open(data_filename(fname)) as data_file:
        return data_file.read()


def write_html(fname, html):
    """Write `html` to `fname`, properly encoded."""
    html = re.sub(r"(\A\s+)|(\s+$)", "", html, flags=re.MULTILINE) + "\n"
    with open(fname, "wb") as fout:
        fout.write(html.encode('ascii', 'xmlcharrefreplace'))


class HtmlDataGeneration:
    """Generate structured data to be turned into HTML reports."""

    EMPTY = "(empty)"

    def __init__(self, cov):
        self.coverage = cov
        self.config = self.coverage.config
        data = self.coverage.get_data()
        self.has_arcs = data.has_arcs()
        if self.config.show_contexts:
            if data.measured_contexts() == {""}:
                self.coverage._warn("No contexts were measured")
        data.set_query_contexts(self.config.report_contexts)

    def data_for_file(self, fr, analysis):
        """Produce the data needed for one file's report."""
        if self.has_arcs:
            missing_branch_arcs = analysis.missing_branch_arcs()
            arcs_executed = analysis.arcs_executed()

        if self.config.show_contexts:
            contexts_by_lineno = analysis.data.contexts_by_lineno(analysis.filename)

        lines = []

        for lineno, tokens in enumerate(fr.source_token_lines(), start=1):
            # Figure out how to mark this line.
            category = None
            short_annotations = []
            long_annotations = []

            if lineno in analysis.excluded:
                category = 'exc'
            elif lineno in analysis.missing:
                category = 'mis'
            elif self.has_arcs and lineno in missing_branch_arcs:
                category = 'par'
                for b in missing_branch_arcs[lineno]:
                    if b < 0:
                        short_annotations.append("exit")
                    else:
                        short_annotations.append(b)
                    long_annotations.append(fr.missing_arc_description(lineno, b, arcs_executed))
            elif lineno in analysis.statements:
                category = 'run'

            contexts = contexts_label = None
            context_list = None
            if category and self.config.show_contexts:
                contexts = sorted(c or self.EMPTY for c in contexts_by_lineno[lineno])
                if contexts == [self.EMPTY]:
                    contexts_label = self.EMPTY
                else:
                    contexts_label = f"{len(contexts)} ctx"
                    context_list = contexts

            lines.append(types.SimpleNamespace(
                tokens=tokens,
                number=lineno,
                category=category,
                statement=(lineno in analysis.statements),
                contexts=contexts,
                contexts_label=contexts_label,
                context_list=context_list,
                short_annotations=short_annotations,
                long_annotations=long_annotations,
            ))

        file_data = types.SimpleNamespace(
            relative_filename=fr.relative_filename(),
            nums=analysis.numbers,
            lines=lines,
        )

        return file_data


class HtmlReporter:
    """HTML reporting."""

    # These files will be copied from the htmlfiles directory to the output
    # directory.
    STATIC_FILES = [
        ("style.css", ""),
        ("jquery.min.js", "jquery"),
        ("jquery.ba-throttle-debounce.min.js", "jquery-throttle-debounce"),
        ("jquery.hotkeys.js", "jquery-hotkeys"),
        ("jquery.isonscreen.js", "jquery-isonscreen"),
        ("jquery.tablesorter.min.js", "jquery-tablesorter"),
        ("jquery-simple-tree-table.js", "jquery-simple-tree-table"),
        ("jquery-simple-tree-table.min.js", "jquery-simple-tree-table"),
        ("simple-tree-table.scss", "jquery-simple-tree-table"),
        ("coverage_html.js", ""),
        ("keybd_closed.png", ""),
        ("keybd_open.png", ""),
        ("favicon_32.png", ""),
    ]

    def __init__(self, cov):
        self.coverage = cov
        self.config = self.coverage.config
        self.directory = self.config.html_dir

        self.skip_covered = self.config.html_skip_covered
        if self.skip_covered is None:
            self.skip_covered = self.config.skip_covered
        self.skip_empty = self.config.html_skip_empty
        if self.skip_empty is None:
            self.skip_empty= self.config.skip_empty

        title = self.config.html_title

        if self.config.extra_css:
            self.extra_css = os.path.basename(self.config.extra_css)
        else:
            self.extra_css = None

        self.data = self.coverage.get_data()
        self.has_arcs = self.data.has_arcs()

        self.file_summaries = []
        self.package_tree = {}
        self.all_files_nums = []
        self.incr = IncrementalChecker(self.directory)
        self.datagen = HtmlDataGeneration(self.coverage)
        self.totals = Numbers(precision=self.config.precision)

        self.template_globals = {
            # Functions available in the templates.
            'escape': escape,
            'pair': pair,
            'len': len,

            # Constants for this report.
            '__url__': coverage.__url__,
            '__version__': coverage.__version__,
            'title': title,
            'time_stamp': format_local_datetime(datetime.datetime.now()),
            'extra_css': self.extra_css,
            'has_arcs': self.has_arcs,
            'show_contexts': self.config.show_contexts,

            # Constants for all reports.
            # These css classes determine which lines are highlighted by default.
            'category': {
                'exc': 'exc show_exc',
                'mis': 'mis show_mis',
                'par': 'par run show_par',
                'run': 'run',
            }
        }
        self.pyfile_html_source = read_data("pyfile.html")
        self.source_tmpl = Templite(self.pyfile_html_source, self.template_globals)

    def report(self, morfs):
        """Generate an HTML report for `morfs`.

        `morfs` is a list of modules or file names.

        """
        # Read the status data and check that this run used the same
        # global data as the last run.
        self.incr.read()
        self.incr.check_global_data(self.config, self.pyfile_html_source)

        # Process all the files.
        for fr, analysis in get_analysis_to_report(self.coverage, morfs):
            self.html_file(fr, analysis)

        if not self.all_files_nums:
            raise CoverageException("No data to report.")

        self.totals = sum(self.all_files_nums)
        self.sum_package_tree()
        self.merge_single_folders()
        # write the package tree summary file
        self.package_tree_file()
        # Write the index file.
        self.index_file()

        self.make_local_static_report_files()
        return self.totals.n_statements and self.totals.pc_covered

    def make_local_static_report_files(self):
        """Make local instances of static files for HTML report."""
        # The files we provide must always be copied.
        for static, pkgdir in self.STATIC_FILES:
            shutil.copyfile(
                data_filename(static, pkgdir),
                os.path.join(self.directory, static)
            )

        # The user may have extra CSS they want copied.
        if self.extra_css:
            shutil.copyfile(
                self.config.extra_css,
                os.path.join(self.directory, self.extra_css)
            )

    def sum_package_tree(self):
        """Sums the file numbers depth first up the package tree"""
        for tree_info in self.package_tree.values():
            if len(tree_info['children']) > 0:
                self._sum_branch(tree_info)

    def _sum_branch(self, tree_info):
        nums = []
        for child_info in tree_info['children'].values():
            if len(child_info['children']) > 0:
                self._sum_branch(child_info)
            nums.append(child_info['nums'])
        tree_info['nums'] = sum(nums)

    def html_file(self, fr, analysis):
        """Generate an HTML file for one source file."""
        rootname = flat_rootname(fr.relative_filename())
        html_filename = rootname + ".html"
        ensure_dir(self.directory)
        html_path = os.path.join(self.directory, html_filename)

        # Get the numbers for this file.
        nums = analysis.numbers
        self.all_files_nums.append(nums)

        if self.skip_covered:
            # Don't report on 100% files.
            no_missing_lines = (nums.n_missing == 0)
            no_missing_branches = (nums.n_partial_branches == 0)
            if no_missing_lines and no_missing_branches:
                # If there's an existing file, remove it.
                file_be_gone(html_path)
                return

        if self.skip_empty:
            # Don't report on empty files.
            if nums.n_statements == 0:
                file_be_gone(html_path)
                return

        # Find out if the file on disk is already correct.
        if self.incr.can_skip_file(self.data, fr, rootname):
            index_info = self.incr.index_info(rootname)
            self.file_summaries.append(index_info)
            self.add_module_to_tree(index_info)
            return

        # Write the HTML page for this file.
        file_data = self.datagen.data_for_file(fr, analysis)
        for ldata in file_data.lines:
            # Build the HTML for the line.
            html = []
            for tok_type, tok_text in ldata.tokens:
                if tok_type == "ws":
                    html.append(escape(tok_text))
                else:
                    tok_html = escape(tok_text) or '&nbsp;'
                    html.append(
                        f'<span class="{tok_type}">{tok_html}</span>'
                    )
            ldata.html = ''.join(html)

            if ldata.short_annotations:
                # 202F is NARROW NO-BREAK SPACE.
                # 219B is RIGHTWARDS ARROW WITH STROKE.
                ldata.annotate = ",&nbsp;&nbsp; ".join(
                    f"{ldata.number}&#x202F;&#x219B;&#x202F;{d}"
                    for d in ldata.short_annotations
                    )
            else:
                ldata.annotate = None

            if ldata.long_annotations:
                longs = ldata.long_annotations
                if len(longs) == 1:
                    ldata.annotate_long = longs[0]
                else:
                    ldata.annotate_long = "{:d} missed branches: {}".format(
                        len(longs),
                        ", ".join(
                            f"{num:d}) {ann_long}"
                            for num, ann_long in enumerate(longs, start=1)
                            ),
                    )
            else:
                ldata.annotate_long = None

            css_classes = []
            if ldata.category:
                css_classes.append(self.template_globals['category'][ldata.category])
            ldata.css_class = ' '.join(css_classes) or "pln"

        html = self.source_tmpl.render(file_data.__dict__)
        write_html(html_path, html)

        # Save this file's information for the index file.
        index_info = {
            'nums': nums,
            'html_filename': html_filename,
            'relative_filename': fr.relative_filename(),
        }
        self.file_summaries.append(index_info)
        self.add_module_to_tree(index_info)
        self.incr.set_index_info(rootname, index_info)

    def add_module_to_tree(self, index_info):
        tree_info = index_info.copy()
        tree_info['is_package'] = False
        tree_info['children'] = {}
        tree_path = tree_info['relative_filename'].split(os.path.sep)  # maybe regexp split on \ or /
        r = tree_path[0]
        branch = self.package_tree.get(r, None)
        tree_depth = len(tree_path)
        if branch is None:
            if tree_depth == 1:
                branch = tree_info
            else:
                branch = self._new_branch(r)
            self.package_tree[r] = branch
        if tree_depth > 1:
            self._add_module_to_branch(branch, tree_path[1:], tree_info)

    def _new_branch(self, rel_filename):
        branch = {
            'nums': Numbers(),
            'html_filename': '',
            'relative_filename': rel_filename,
            'is_package': True,
            'children': {},
        }
        return branch

    def _add_module_to_branch(self, parent, tree_path, tree_info):
        """Recursively navigate module tree adding nodes as required """
        r = tree_path[0]
        branch = parent['children'].get(r, None)
        tree_depth = len(tree_path)
        if branch is None:
            if tree_depth == 1:
                branch = tree_info
                branch['relative_filename'] = r
            else:
                branch = self._new_branch(r)
            parent['children'][r] = branch
        if tree_depth > 1:
            self._add_module_to_branch(branch, tree_path[1:], tree_info)

    def merge_single_folders(self):
        """ Convert nested single folders into a single row.
        So that this:
        + a
            + b
                + c
                    file1.py
                    file2.py
        becomes
        + a/b/c
            file1.py
            file2.py
        """
        for tree_info in self.package_tree.values():
            self._merge_branch_folders(tree_info)

    def _merge_branch_folders(self, tree_info):
        for child_info in tree_info['children'].values():
            self._merge_branch_folders(child_info)
        if len(tree_info['children']) == 1:
            path, child_info = next(iter(tree_info['children'].items()))
            if child_info['children']:
                tree_info['children'] = child_info['children']
                new_path = os.path.sep.join((tree_info['relative_filename'],
                                             child_info['relative_filename']))
                tree_info['relative_filename'] = new_path

    def package_tree_to_list(self):
        """Convert package tree into a list adding data-node identifiers for javascript"""
        package_list = []
        for i, (_, tree_info) in enumerate(sorted(self.package_tree.items()), start=1):
            tree_info['node_pid'] = None
            self._add_branch_to_list(tree_info, package_list, str(i))
        for tree_info in package_list:
            tree_info['is_module'] = not tree_info['is_package']
        return package_list

    def _add_branch_to_list(self, tree_info, package_list, node_id):
        tree_info['node_id'] = node_id
        package_list.append(tree_info)
        for i, (_, child_info) in enumerate(sorted(tree_info['children'].items()), start=1):
            child_info['node_pid'] = node_id
            child_id = '{}.{}'.format(node_id, i)
            self._add_branch_to_list(child_info, package_list, child_id)

    def package_tree_file(self):
        """Write the package_tree.html file for this report"""
        tree_tmpl = Templite(read_data("package_tree.html"), self.template_globals)
        tree_list = self.package_tree_to_list()
        html = tree_tmpl.render({
            'files': tree_list,
            'totals': self.totals,
        })

        write_html(os.path.join(self.directory, "package_tree.html"), html)

    def index_file(self):
        """Write the index.html file for this report."""
        index_tmpl = Templite(read_data("index.html"), self.template_globals)

        html = index_tmpl.render({
            'files': self.file_summaries,
            'totals': self.totals,
        })

        write_html(os.path.join(self.directory, "index.html"), html)

        # Write the latest hashes for next time.
        self.incr.write()


class IncrementalChecker:
    """Logic and data to support incremental reporting."""

    STATUS_FILE = "status.json"
    STATUS_FORMAT = 2

    #           pylint: disable=wrong-spelling-in-comment,useless-suppression
    #  The data looks like:
    #
    #  {
    #      "format": 2,
    #      "globals": "540ee119c15d52a68a53fe6f0897346d",
    #      "version": "4.0a1",
    #      "files": {
    #          "cogapp___init__": {
    #              "hash": "e45581a5b48f879f301c0f30bf77a50c",
    #              "index": {
    #                  "html_filename": "cogapp___init__.html",
    #                  "relative_filename": "cogapp/__init__",
    #                  "nums": [ 1, 14, 0, 0, 0, 0, 0 ]
    #              }
    #          },
    #          ...
    #          "cogapp_whiteutils": {
    #              "hash": "8504bb427fc488c4176809ded0277d51",
    #              "index": {
    #                  "html_filename": "cogapp_whiteutils.html",
    #                  "relative_filename": "cogapp/whiteutils",
    #                  "nums": [ 1, 59, 0, 1, 28, 2, 2 ]
    #              }
    #          }
    #      }
    #  }

    def __init__(self, directory):
        self.directory = directory
        self.reset()

    def reset(self):
        """Initialize to empty. Causes all files to be reported."""
        self.globals = ''
        self.files = {}

    def read(self):
        """Read the information we stored last time."""
        usable = False
        try:
            status_file = os.path.join(self.directory, self.STATUS_FILE)
            with open(status_file) as fstatus:
                status = json.load(fstatus)
        except (OSError, ValueError):
            usable = False
        else:
            usable = True
            if status['format'] != self.STATUS_FORMAT:
                usable = False
            elif status['version'] != coverage.__version__:
                usable = False

        if usable:
            self.files = {}
            for filename, fileinfo in status['files'].items():
                fileinfo['index']['nums'] = Numbers(*fileinfo['index']['nums'])
                self.files[filename] = fileinfo
            self.globals = status['globals']
        else:
            self.reset()

    def write(self):
        """Write the current status."""
        status_file = os.path.join(self.directory, self.STATUS_FILE)
        files = {}
        for filename, fileinfo in self.files.items():
            fileinfo['index']['nums'] = fileinfo['index']['nums'].init_args()
            files[filename] = fileinfo

        status = {
            'format': self.STATUS_FORMAT,
            'version': coverage.__version__,
            'globals': self.globals,
            'files': files,
        }
        with open(status_file, "w") as fout:
            json.dump(status, fout, separators=(',', ':'))

    def check_global_data(self, *data):
        """Check the global data that can affect incremental reporting."""
        m = Hasher()
        for d in data:
            m.update(d)
        these_globals = m.hexdigest()
        if self.globals != these_globals:
            self.reset()
            self.globals = these_globals

    def can_skip_file(self, data, fr, rootname):
        """Can we skip reporting this file?

        `data` is a CoverageData object, `fr` is a `FileReporter`, and
        `rootname` is the name being used for the file.
        """
        m = Hasher()
        m.update(fr.source().encode('utf-8'))
        add_data_to_hash(data, fr.filename, m)
        this_hash = m.hexdigest()

        that_hash = self.file_hash(rootname)

        if this_hash == that_hash:
            # Nothing has changed to require the file to be reported again.
            return True
        else:
            self.set_file_hash(rootname, this_hash)
            return False

    def file_hash(self, fname):
        """Get the hash of `fname`'s contents."""
        return self.files.get(fname, {}).get('hash', '')

    def set_file_hash(self, fname, val):
        """Set the hash of `fname`'s contents."""
        self.files.setdefault(fname, {})['hash'] = val

    def index_info(self, fname):
        """Get the information for index.html for `fname`."""
        return self.files.get(fname, {}).get('index', {})

    def set_index_info(self, fname, info):
        """Set the information for index.html for `fname`."""
        self.files.setdefault(fname, {})['index'] = info


# Helpers for templates and generating HTML

def escape(t):
    """HTML-escape the text in `t`.

    This is only suitable for HTML text, not attributes.

    """
    # Convert HTML special chars into HTML entities.
    return t.replace("&", "&amp;").replace("<", "&lt;")


def pair(ratio):
    """Format a pair of numbers so JavaScript can read them in an attribute."""
    return "%s %s" % ratio
