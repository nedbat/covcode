# Licensed under the Apache License: http://www.apache.org/licenses/LICENSE-2.0
# For details: https://github.com/nedbat/coveragepy/blob/master/NOTICE.txt

"""Test cmdline.py for coverage.py."""

import os
import pprint
import sys
import textwrap

from unittest import mock
import pytest

import coverage
import coverage.cmdline
from coverage import env
from coverage.config import CoverageConfig
from coverage.data import CoverageData
from coverage.exceptions import ExceptionDuringRun
from coverage.version import __url__

from tests.coveragetest import CoverageTest, OK, ERR, command_line


class BaseCmdLineTest(CoverageTest):
    """Tests of execution paths through the command line interpreter."""

    run_in_temp_dir = False

    # Make a dict mapping function names to the default values that cmdline.py
    # uses when calling the function.
    _defaults = mock.Mock()
    _defaults.Coverage().annotate(
        directory=None, ignore_errors=False, include=None, omit=None, morfs=[],
        contexts=None,
    )
    _defaults.Coverage().html_report(
        directory=None, ignore_errors=False, include=None, omit=None, morfs=[],
        skip_covered=False, show_contexts=False, title=None, contexts=None,
        skip_empty=False, precision=None,
    )
    _defaults.Coverage().report(
        ignore_errors=False, include=None, omit=None, morfs=[],
        show_missing=False, skip_covered=False, contexts=None, skip_empty=False, precision=None,
        sort=None,
    )
    _defaults.Coverage().xml_report(
        ignore_errors=False, include=None, omit=None, morfs=[], outfile=None,
        contexts=None, skip_empty=False,
    )
    _defaults.Coverage().json_report(
        ignore_errors=False, include=None, omit=None, morfs=[], outfile=None,
        contexts=None, pretty_print=False, show_contexts=False,
    )
    _defaults.Coverage(
        cover_pylib=False, data_suffix=False, timid=False, branch=False,
        config_file=True, source=None, include=None, omit=None, debug=None,
        concurrency=None, check_preimported=True, context=None,
    )

    DEFAULT_KWARGS = {name: kw for name, _, kw in _defaults.mock_calls}

    def model_object(self):
        """Return a Mock suitable for use in CoverageScript."""
        mk = mock.Mock()

        cov = mk.Coverage.return_value

        # The mock needs options.
        mk.config = CoverageConfig()
        cov.get_option = mk.config.get_option
        cov.set_option = mk.config.set_option

        # Get the type right for the result of reporting.
        cov.report.return_value = 50.0
        cov.html_report.return_value = 50.0
        cov.xml_report.return_value = 50.0
        cov.json_report.return_value = 50.0

        return mk

    # Global names in cmdline.py that will be mocked during the tests.
    MOCK_GLOBALS = ['Coverage', 'PyRunner']

    def mock_command_line(self, args, options=None):
        """Run `args` through the command line, with a Mock.

        `options` is a dict of names and values to pass to `set_option`.

        Returns the Mock it used and the status code returned.

        """
        mk = self.model_object()

        if options is not None:
            for name, value in options.items():
                mk.config.set_option(name, value)

        patchers = [
            mock.patch("coverage.cmdline."+name, getattr(mk, name))
            for name in self.MOCK_GLOBALS
            ]
        for patcher in patchers:
            patcher.start()
        try:
            ret = command_line(args)
        finally:
            for patcher in patchers:
                patcher.stop()

        return mk, ret

    def cmd_executes(self, args, code, ret=OK, options=None):
        """Assert that the `args` end up executing the sequence in `code`."""
        called, status = self.mock_command_line(args, options=options)
        assert status == ret, f"Wrong status: got {status!r}, wanted {ret!r}"

        # Remove all indentation, and execute with mock globals
        code = textwrap.dedent(code)
        expected = self.model_object()
        globs = {n: getattr(expected, n) for n in self.MOCK_GLOBALS}
        code_obj = compile(code, "<code>", "exec")
        eval(code_obj, globs, {})                           # pylint: disable=eval-used

        # Many of our functions take a lot of arguments, and cmdline.py
        # calls them with many.  But most of them are just the defaults, which
        # we don't want to have to repeat in all tests.  For each call, apply
        # the defaults.  This lets the tests just mention the interesting ones.
        for name, _, kwargs in expected.mock_calls:
            for k, v in self.DEFAULT_KWARGS.get(name, {}).items():
                kwargs.setdefault(k, v)

        self.assert_same_mock_calls(expected, called)

    def cmd_executes_same(self, args1, args2):
        """Assert that the `args1` executes the same as `args2`."""
        m1, r1 = self.mock_command_line(args1)
        m2, r2 = self.mock_command_line(args2)
        assert r1 == r2
        self.assert_same_mock_calls(m1, m2)

    def assert_same_mock_calls(self, m1, m2):
        """Assert that `m1.mock_calls` and `m2.mock_calls` are the same."""
        # Use a real equality comparison, but if it fails, use a nicer assert
        # so we can tell what's going on.  We have to use the real == first due
        # to CmdOptionParser.__eq__
        if m1.mock_calls != m2.mock_calls:
            pp1 = pprint.pformat(m1.mock_calls)
            pp2 = pprint.pformat(m2.mock_calls)
            assert pp1+'\n' == pp2+'\n'

    def cmd_outputs(self, args, output, ret=ERR):
        """Run a command line, and check that it prints the right help.

        Only the last function call in the mock is checked, which should be the
        help message that we want to see.

        """
        mk, status = self.mock_command_line(args)
        assert status == ret, f"Wrong status: got {status}, wanted {ret}"
        cmd_out, cmd_err = self.stdouterr()
        assert output in cmd_out + cmd_err, (
            f"output doesn't contain {output}:\nOut:\n{cmd_out}\nErr:\n{cmd_err}"
        )

class BaseCmdLineTestTest(BaseCmdLineTest):
    """Tests that our BaseCmdLineTest helpers work."""
    def test_cmd_executes_same(self):
        # All the other tests here use self.cmd_executes_same in successful
        # ways, so here we just check that it fails.
        with pytest.raises(AssertionError):
            self.cmd_executes_same("run", "debug premain")


class CmdLineTest(BaseCmdLineTest):
    """Tests of the coverage.py command line."""

    def test_annotate(self):
        # coverage annotate [-d DIR] [-i] [--omit DIR,...] [FILE1 FILE2 ...]
        self.cmd_executes("annotate", """\
            cov = Coverage()
            cov.load()
            cov.annotate()
            """)
        self.cmd_executes("annotate -d dir1", """\
            cov = Coverage()
            cov.load()
            cov.annotate(directory="dir1")
            """)
        self.cmd_executes("annotate -i", """\
            cov = Coverage()
            cov.load()
            cov.annotate(ignore_errors=True)
            """)
        self.cmd_executes("annotate --omit fooey", """\
            cov = Coverage(omit=["fooey"])
            cov.load()
            cov.annotate(omit=["fooey"])
            """)
        self.cmd_executes("annotate --omit fooey,booey", """\
            cov = Coverage(omit=["fooey", "booey"])
            cov.load()
            cov.annotate(omit=["fooey", "booey"])
            """)
        self.cmd_executes("annotate mod1", """\
            cov = Coverage()
            cov.load()
            cov.annotate(morfs=["mod1"])
            """)
        self.cmd_executes("annotate mod1 mod2 mod3", """\
            cov = Coverage()
            cov.load()
            cov.annotate(morfs=["mod1", "mod2", "mod3"])
            """)

    def test_combine(self):
        # coverage combine with args
        self.cmd_executes("combine datadir1", """\
            cov = Coverage()
            cov.combine(["datadir1"], strict=True, keep=False)
            cov.save()
            """)
        # coverage combine, appending
        self.cmd_executes("combine --append datadir1", """\
            cov = Coverage()
            cov.load()
            cov.combine(["datadir1"], strict=True, keep=False)
            cov.save()
            """)
        # coverage combine without args
        self.cmd_executes("combine", """\
            cov = Coverage()
            cov.combine(None, strict=True, keep=False)
            cov.save()
            """)

    def test_combine_doesnt_confuse_options_with_args(self):
        # https://github.com/nedbat/coveragepy/issues/385
        self.cmd_executes("combine --rcfile cov.ini", """\
            cov = Coverage(config_file='cov.ini')
            cov.combine(None, strict=True, keep=False)
            cov.save()
            """)
        self.cmd_executes("combine --rcfile cov.ini data1 data2/more", """\
            cov = Coverage(config_file='cov.ini')
            cov.combine(["data1", "data2/more"], strict=True, keep=False)
            cov.save()
            """)

    def test_debug(self):
        self.cmd_outputs("debug", "the following arguments are required: topic")
        self.cmd_outputs("debug foo", "argument topic: invalid choice: 'foo' (choose from 'data', 'sys', 'config', 'premain')")

    def test_debug_sys(self):
        self.command_line("debug sys")
        out = self.stdout()
        assert "version:" in out, f"Full output:\n{out}"
        assert "data_file:" in out, f"Full output:\n{out}"

    def test_debug_config(self):
        self.command_line("debug config")
        out = self.stdout()
        assert "cover_pylib:" in out, f"Full output:\n{out}"
        assert "skip_covered:" in out, f"Full output:\n{out}"
        assert "skip_empty:" in out, f"Full output:\n{out}"

    def test_erase(self):
        # coverage erase
        self.cmd_executes("erase", """\
            cov = Coverage()
            cov.erase()
            """)

    def test_version(self):
        # coverage --version
        self.cmd_outputs("--version", output="Coverage.py, version", ret=OK)

    def test_help_option(self):
        # coverage -h
        self.cmd_outputs("-h", output="Measure, collect, and report", ret=OK)
        self.cmd_outputs("--help", output="Measure, collect, and report", ret=OK)

    def test_help_command(self):
        self.cmd_outputs("help", output="Measure, collect, and report", ret=OK)

    def test_cmd_help(self):
        self.cmd_outputs("run --help", "Run a Python program", ret=OK)
        self.cmd_outputs("help run", "Run a Python program", ret=OK)

    def test_html(self):
        # coverage html -d DIR [-i] [--omit DIR,...] [FILE1 FILE2 ...]
        self.cmd_executes("html", """\
            cov = Coverage()
            cov.load()
            cov.html_report()
            """)
        self.cmd_executes("html -d dir1", """\
            cov = Coverage()
            cov.load()
            cov.html_report(directory="dir1")
            """)
        self.cmd_executes("html -i", """\
            cov = Coverage()
            cov.load()
            cov.html_report(ignore_errors=True)
            """)
        self.cmd_executes("html --omit fooey", """\
            cov = Coverage(omit=["fooey"])
            cov.load()
            cov.html_report(omit=["fooey"])
            """)
        self.cmd_executes("html --omit fooey,booey", """\
            cov = Coverage(omit=["fooey", "booey"])
            cov.load()
            cov.html_report(omit=["fooey", "booey"])
            """)
        self.cmd_executes("html mod1", """\
            cov = Coverage()
            cov.load()
            cov.html_report(morfs=["mod1"])
            """)
        self.cmd_executes("html mod1 mod2 mod3", """\
            cov = Coverage()
            cov.load()
            cov.html_report(morfs=["mod1", "mod2", "mod3"])
            """)
        self.cmd_executes("html --precision=3", """\
            cov = Coverage()
            cov.load()
            cov.html_report(precision=3)
            """)
        self.cmd_executes("html --title=Hello_there", """\
            cov = Coverage()
            cov.load()
            cov.html_report(title='Hello_there')
            """)

    def test_report(self):
        # coverage report [-m] [-i] [-o DIR,...] [FILE1 FILE2 ...]
        self.cmd_executes("report", """\
            cov = Coverage()
            cov.load()
            cov.report(show_missing=False)
            """)
        self.cmd_executes("report -i", """\
            cov = Coverage()
            cov.load()
            cov.report(ignore_errors=True)
            """)
        self.cmd_executes("report -m", """\
            cov = Coverage()
            cov.load()
            cov.report(show_missing=True)
            """)
        self.cmd_executes("report --omit fooey", """\
            cov = Coverage(omit=["fooey"])
            cov.load()
            cov.report(omit=["fooey"])
            """)
        self.cmd_executes("report --omit fooey,booey", """\
            cov = Coverage(omit=["fooey", "booey"])
            cov.load()
            cov.report(omit=["fooey", "booey"])
            """)
        self.cmd_executes("report mod1", """\
            cov = Coverage()
            cov.load()
            cov.report(morfs=["mod1"])
            """)
        self.cmd_executes("report mod1 mod2 mod3", """\
            cov = Coverage()
            cov.load()
            cov.report(morfs=["mod1", "mod2", "mod3"])
            """)
        self.cmd_executes("report --precision=7", """\
            cov = Coverage()
            cov.load()
            cov.report(precision=7)
            """)
        self.cmd_executes("report --skip-covered", """\
            cov = Coverage()
            cov.load()
            cov.report(skip_covered=True)
            """)
        self.cmd_executes("report --skip-covered --no-skip-covered", """\
            cov = Coverage()
            cov.load()
            cov.report(skip_covered=False)
            """)
        self.cmd_executes("report --no-skip-covered", """\
            cov = Coverage()
            cov.load()
            cov.report(skip_covered=False)
            """)
        self.cmd_executes("report --skip-empty", """\
            cov = Coverage()
            cov.load()
            cov.report(skip_empty=True)
            """)
        self.cmd_executes("report --contexts=foo,bar", """\
            cov = Coverage()
            cov.load()
            cov.report(contexts=["foo", "bar"])
            """)
        self.cmd_executes("report --sort=-foo", """\
            cov = Coverage()
            cov.load()
            cov.report(sort='-foo')
            """)

    def test_run(self):
        # coverage run [-p] [-L] [--timid] MODULE.py [ARG1 ARG2 ...]

        # run calls coverage.erase first.
        self.cmd_executes("run foo.py", """\
            cov = Coverage()
            runner = PyRunner(['foo.py'], as_module=False)
            runner.prepare()
            cov.start()
            runner.run()
            cov.stop()
            cov.save()
            """)
        # run -a combines with an existing data file before saving.
        self.cmd_executes("run -a foo.py", """\
            cov = Coverage()
            runner = PyRunner(['foo.py'], as_module=False)
            runner.prepare()
            cov.load()
            cov.start()
            runner.run()
            cov.stop()
            cov.save()
            """)
        # --timid sets a flag, and program arguments get passed through.
        self.cmd_executes("run --timid foo.py abc 123", """\
            cov = Coverage(timid=True)
            runner = PyRunner(['foo.py', 'abc', '123'], as_module=False)
            runner.prepare()
            cov.start()
            runner.run()
            cov.stop()
            cov.save()
            """)
        # -L sets a flag, and flags for the program don't confuse us.
        self.cmd_executes("run -p -L foo.py -a -b", """\
            cov = Coverage(cover_pylib=True, data_suffix=True)
            runner = PyRunner(['foo.py', '-a', '-b'], as_module=False)
            runner.prepare()
            cov.start()
            runner.run()
            cov.stop()
            cov.save()
            """)
        self.cmd_executes("run --branch foo.py", """\
            cov = Coverage(branch=True)
            runner = PyRunner(['foo.py'], as_module=False)
            runner.prepare()
            cov.start()
            runner.run()
            cov.stop()
            cov.save()
            """)
        self.cmd_executes("run --rcfile=myrc.rc foo.py", """\
            cov = Coverage(config_file="myrc.rc")
            runner = PyRunner(['foo.py'], as_module=False)
            runner.prepare()
            cov.start()
            runner.run()
            cov.stop()
            cov.save()
            """)
        self.cmd_executes("run --include=pre1,pre2 foo.py", """\
            cov = Coverage(include=["pre1", "pre2"])
            runner = PyRunner(['foo.py'], as_module=False)
            runner.prepare()
            cov.start()
            runner.run()
            cov.stop()
            cov.save()
            """)
        self.cmd_executes("run --omit=opre1,opre2 foo.py", """\
            cov = Coverage(omit=["opre1", "opre2"])
            runner = PyRunner(['foo.py'], as_module=False)
            runner.prepare()
            cov.start()
            runner.run()
            cov.stop()
            cov.save()
            """)
        self.cmd_executes("run --include=pre1,pre2 --omit=opre1,opre2 foo.py", """\
            cov = Coverage(include=["pre1", "pre2"], omit=["opre1", "opre2"])
            runner = PyRunner(['foo.py'], as_module=False)
            runner.prepare()
            cov.start()
            runner.run()
            cov.stop()
            cov.save()
            """)
        self.cmd_executes("run --source=quux,hi.there,/home/bar foo.py", """\
            cov = Coverage(source=["quux", "hi.there", "/home/bar"])
            runner = PyRunner(['foo.py'], as_module=False)
            runner.prepare()
            cov.start()
            runner.run()
            cov.stop()
            cov.save()
            """)
        self.cmd_executes("run --concurrency=gevent foo.py", """\
            cov = Coverage(concurrency='gevent')
            runner = PyRunner(['foo.py'], as_module=False)
            runner.prepare()
            cov.start()
            runner.run()
            cov.stop()
            cov.save()
            """)
        self.cmd_executes("run --concurrency=multiprocessing foo.py", """\
            cov = Coverage(concurrency='multiprocessing')
            runner = PyRunner(['foo.py'], as_module=False)
            runner.prepare()
            cov.start()
            runner.run()
            cov.stop()
            cov.save()
            """)

    def test_bad_concurrency(self):
        self.command_line("run --concurrency=nothing", ret=ERR)
        err = self.stderr()
        assert "argument --concurrency: invalid choice: 'nothing'" in err, f"Full output:\n{err}"

    def test_no_multiple_concurrency(self):
        # You can't use multiple concurrency values on the command line.
        # I would like to have a better message about not allowing multiple
        # values for this option, but optparse is not that flexible.
        self.command_line("run --concurrency=multiprocessing,gevent foo.py", ret=ERR)
        err = self.stderr()
        assert "argument --concurrency: invalid choice: 'multiprocessing,gevent'" in err, f"Full output:\n{err}"

    def test_multiprocessing_needs_config_file(self):
        # You can't use command-line args to add options to multiprocessing
        # runs, since they won't make it to the subprocesses. You need to use a
        # config file.
        self.command_line("run --concurrency=multiprocessing --branch foo.py", ret=ERR)
        msg = "Options affecting multiprocessing must only be specified in a configuration file."
        err = self.stderr()
        assert msg in err, f"Full output:\n{err}"
        assert "Remove --branch from the command line." in err, f"Full output:\n{err}"

    def test_run_debug(self):
        self.cmd_executes("run --debug=opt1 foo.py", """\
            cov = Coverage(debug=["opt1"])
            runner = PyRunner(['foo.py'], as_module=False)
            runner.prepare()
            cov.start()
            runner.run()
            cov.stop()
            cov.save()
            """)
        self.cmd_executes("run --debug=opt1,opt2 foo.py", """\
            cov = Coverage(debug=["opt1","opt2"])
            runner = PyRunner(['foo.py'], as_module=False)
            runner.prepare()
            cov.start()
            runner.run()
            cov.stop()
            cov.save()
            """)

    def test_run_module(self):
        self.cmd_executes("run -m mymodule", """\
            cov = Coverage()
            runner = PyRunner(['mymodule'], as_module=True)
            runner.prepare()
            cov.start()
            runner.run()
            cov.stop()
            cov.save()
            """)
        self.cmd_executes("run -m mymodule -qq arg1 arg2", """\
            cov = Coverage()
            runner = PyRunner(['mymodule', '-qq', 'arg1', 'arg2'], as_module=True)
            runner.prepare()
            cov.start()
            runner.run()
            cov.stop()
            cov.save()
            """)
        self.cmd_executes("run --branch -m mymodule", """\
            cov = Coverage(branch=True)
            runner = PyRunner(['mymodule'], as_module=True)
            runner.prepare()
            cov.start()
            runner.run()
            cov.stop()
            cov.save()
            """)
        self.cmd_executes_same("run -m mymodule", "run --module mymodule")

    def test_run_from_config(self):
        options = {"run:command_line": "myprog.py a 123 'a quoted thing' xyz"}
        self.cmd_executes("run", """\
            cov = Coverage()
            runner = PyRunner(['myprog.py', 'a', '123', 'a quoted thing', 'xyz'], as_module=False)
            runner.prepare()
            cov.start()
            runner.run()
            cov.stop()
            cov.save()
            """,
            options=options,
            )

    def test_run_module_from_config(self):
        self.cmd_executes("run", """\
            cov = Coverage()
            runner = PyRunner(['mymodule', 'thing1', 'thing2'], as_module=True)
            runner.prepare()
            cov.start()
            runner.run()
            cov.stop()
            cov.save()
            """,
            options={"run:command_line": "-m mymodule thing1 thing2"},
            )

    def test_run_from_config_but_empty(self):
        self.cmd_executes("run", """\
            cov = Coverage()
            show_help('Nothing to do.')
            """,
            ret=ERR,
            options={"run:command_line": ""},
            )

    def test_cant_append_parallel(self):
        self.command_line("run --append --parallel-mode foo.py", ret=ERR)
        assert "Can't append to data files in parallel mode." in self.stderr()

    def test_xml(self):
        # coverage xml [-i] [--omit DIR,...] [FILE1 FILE2 ...]
        self.cmd_executes("xml", """\
            cov = Coverage()
            cov.load()
            cov.xml_report()
            """)
        self.cmd_executes("xml -i", """\
            cov = Coverage()
            cov.load()
            cov.xml_report(ignore_errors=True)
            """)
        self.cmd_executes("xml -o myxml.foo", """\
            cov = Coverage()
            cov.load()
            cov.xml_report(outfile="myxml.foo")
            """)
        self.cmd_executes("xml -o -", """\
            cov = Coverage()
            cov.load()
            cov.xml_report(outfile="-")
            """)
        self.cmd_executes("xml --omit fooey", """\
            cov = Coverage(omit=["fooey"])
            cov.load()
            cov.xml_report(omit=["fooey"])
            """)
        self.cmd_executes("xml --omit fooey,booey", """\
            cov = Coverage(omit=["fooey", "booey"])
            cov.load()
            cov.xml_report(omit=["fooey", "booey"])
            """)
        self.cmd_executes("xml mod1", """\
            cov = Coverage()
            cov.load()
            cov.xml_report(morfs=["mod1"])
            """)
        self.cmd_executes("xml mod1 mod2 mod3", """\
            cov = Coverage()
            cov.load()
            cov.xml_report(morfs=["mod1", "mod2", "mod3"])
            """)

    def test_json(self):
        # coverage json [-i] [--omit DIR,...] [FILE1 FILE2 ...]
        self.cmd_executes("json", """\
            cov = Coverage()
            cov.load()
            cov.json_report()
            """)
        self.cmd_executes("json --pretty-print", """\
            cov = Coverage()
            cov.load()
            cov.json_report(pretty_print=True)
            """)
        self.cmd_executes("json --pretty-print --show-contexts", """\
            cov = Coverage()
            cov.load()
            cov.json_report(pretty_print=True, show_contexts=True)
            """)
        self.cmd_executes("json -i", """\
            cov = Coverage()
            cov.load()
            cov.json_report(ignore_errors=True)
            """)
        self.cmd_executes("json -o myjson.foo", """\
            cov = Coverage()
            cov.load()
            cov.json_report(outfile="myjson.foo")
            """)
        self.cmd_executes("json -o -", """\
            cov = Coverage()
            cov.load()
            cov.json_report(outfile="-")
            """)
        self.cmd_executes("json --omit fooey", """\
            cov = Coverage(omit=["fooey"])
            cov.load()
            cov.json_report(omit=["fooey"])
            """)
        self.cmd_executes("json --omit fooey,booey", """\
            cov = Coverage(omit=["fooey", "booey"])
            cov.load()
            cov.json_report(omit=["fooey", "booey"])
            """)
        self.cmd_executes("json mod1", """\
            cov = Coverage()
            cov.load()
            cov.json_report(morfs=["mod1"])
            """)
        self.cmd_executes("json mod1 mod2 mod3", """\
            cov = Coverage()
            cov.load()
            cov.json_report(morfs=["mod1", "mod2", "mod3"])
            """)

    def test_no_arguments_at_all(self):
        self.cmd_outputs("", output="Code coverage for Python", ret=OK)

    def test_bad_command(self):
        self.cmd_outputs("xyzzy", "invalid choice: 'xyzzy'")


class CmdLineWithFilesTest(BaseCmdLineTest):
    """Test the command line in ways that need temp files."""

    run_in_temp_dir = True

    def test_debug_data(self):
        data = CoverageData()
        data.add_lines({
            "file1.py": dict.fromkeys(range(1, 18)),
            "file2.py": dict.fromkeys(range(1, 24)),
        })
        data.add_file_tracers({"file1.py": "a_plugin"})
        data.write()

        self.command_line("debug data")
        assert self.stdout() == textwrap.dedent("""\
            -- data ------------------------------------------------------
            path: FILENAME
            has_arcs: False

            2 files:
            file1.py: 17 lines [a_plugin]
            file2.py: 23 lines
            """).replace("FILENAME", data.data_filename())

    def test_debug_data_with_no_data(self):
        data = CoverageData()
        self.command_line("debug data")
        assert self.stdout() == textwrap.dedent("""\
            -- data ------------------------------------------------------
            path: FILENAME
            No data collected
            """).replace("FILENAME", data.data_filename())


class CmdLineStdoutTest(BaseCmdLineTest):
    """Test the command line with real stdout output."""

    def test_minimum_help(self):
        self.command_line("")
        out = self.stdout()
        assert "Code coverage for Python" in out, f"Full output:\n{out}"
        assert out.count("\n") < 4

    def test_version(self):
        self.command_line("--version")
        out = self.stdout()
        assert "ersion " in out, f"Full output:\n{out}"
        if env.C_TRACER:
            assert "with C extension" in out, f"Full output:\n{out}"
        else:
            assert "without C extension" in out, f"Full output:\n{out}"
        assert out.count("\n") < 4

    @pytest.mark.skipif(env.JYTHON, reason="Jython gets mad if you patch sys.argv")
    def test_help_contains_command_name(self):
        # Command name should be present in help output.
        fake_command_path = "lorem/ipsum/dolor".replace("/", os.sep)
        expected_command_name = "dolor"
        fake_argv = [fake_command_path, "sit", "amet"]
        with mock.patch.object(sys, 'argv', new=fake_argv):
            self.command_line("help")
        out = self.stdout()
        assert expected_command_name in out, f"Full output:\n{out}"

    @pytest.mark.skipif(env.JYTHON, reason="Jython gets mad if you patch sys.argv")
    def test_help_contains_command_name_from_package(self):
        # Command package name should be present in help output.
        #
        # When the main module is actually a package's `__main__` module, the resulting command line
        # has the `__main__.py` file's patch as the command name. Instead, the command name should
        # be derived from the package name.

        fake_command_path = "lorem/ipsum/dolor/__main__.py".replace("/", os.sep)
        expected_command_name = "dolor"
        fake_argv = [fake_command_path, "sit", "amet"]
        with mock.patch.object(sys, 'argv', new=fake_argv):
            self.command_line("help")
        out = self.stdout()
        assert expected_command_name in out, f"Full output:\n{out}"

    def test_help(self):
        self.command_line("help")
        lines = self.stdout().splitlines()
        assert len(lines) > 10
        assert lines[-1] == f"Full documentation is at {__url__}"

    def test_cmd_help(self):
        self.command_line("help run")
        out = self.stdout()
        lines = out.splitlines()
        assert "PYFILE" in out
        assert "--timid" in out, f"Full output:\n{out}"
        assert len(lines) > 20
        assert lines[-1] == f"Full documentation is at {__url__}"

    def test_unknown_topic(self):
        self.command_line("help foobar", ret=ERR)
        lines = self.stderr().splitlines()
        assert "argument topic: invalid choice: 'foobar'" in lines[2]

    def test_error(self):
        self.command_line("fooey kablooey", ret=ERR)
        err = self.stderr()
        assert "fooey" in err, f"Full output:\n{err}"
        assert "help" in err, f"Full output:\n{err}"

    def test_doc_url(self):
        assert __url__.startswith("https://coverage.readthedocs.io")


class CmdMainTest(CoverageTest):
    """Tests of coverage.cmdline.main(), using mocking for isolation."""

    run_in_temp_dir = False

    class CoverageScriptStub:
        """A stub for coverage.cmdline.CoverageScript, used by CmdMainTest."""

        def command_line(self, argv):
            """Stub for command_line, the arg determines what it will do."""
            if argv[0] == 'hello':
                print("Hello, world!")
            elif argv[0] == 'raise':
                try:
                    raise Exception("oh noes!")
                except:
                    raise ExceptionDuringRun(*sys.exc_info())
            elif argv[0] == 'internalraise':
                raise ValueError("coverage is broken")
            elif argv[0] == 'exit':
                sys.exit(23)
            else:
                raise AssertionError(f"Bad CoverageScriptStub: {argv!r}")
            return 0

    def setup_test(self):
        super().setup_test()
        old_CoverageScript = coverage.cmdline.CoverageScript
        coverage.cmdline.CoverageScript = self.CoverageScriptStub
        self.addCleanup(setattr, coverage.cmdline, 'CoverageScript', old_CoverageScript)

    def test_normal(self):
        ret = coverage.cmdline.main(['hello'])
        assert ret == 0
        assert self.stdout() == "Hello, world!\n"

    def test_raise(self):
        ret = coverage.cmdline.main(['raise'])
        assert ret == 1
        out, err = self.stdouterr()
        assert out == ""
        err = err.split('\n')
        assert err[0] == 'Traceback (most recent call last):'
        assert err[-3] == '    raise Exception("oh noes!")'
        assert err[-2] == 'Exception: oh noes!'

    def test_internalraise(self):
        with pytest.raises(ValueError, match="coverage is broken"):
            coverage.cmdline.main(['internalraise'])

    def test_exit(self):
        ret = coverage.cmdline.main(['exit'])
        assert ret == 23


class CoverageReportingFake:
    """A fake Coverage.coverage test double."""
    # pylint: disable=missing-function-docstring
    def __init__(self, report_result, html_result, xml_result, json_report):
        self.config = CoverageConfig()
        self.report_result = report_result
        self.html_result = html_result
        self.xml_result = xml_result
        self.json_result = json_report

    def set_option(self, optname, optvalue):
        self.config.set_option(optname, optvalue)

    def get_option(self, optname):
        return self.config.get_option(optname)

    def load(self):
        pass

    def report(self, *args_unused, **kwargs_unused):
        return self.report_result

    def html_report(self, *args_unused, **kwargs_unused):
        return self.html_result

    def xml_report(self, *args_unused, **kwargs_unused):
        return self.xml_result

    def json_report(self, *args_unused, **kwargs_unused):
        return self.json_result


@pytest.mark.parametrize("results, fail_under, cmd, ret", [
    # Command-line switch properly checks the result of reporting functions.
    ((20, 30, 40, 50), None, "report --fail-under=19", 0),
    ((20, 30, 40, 50), None, "report --fail-under=21", 2),
    ((20, 30, 40, 50), None, "html --fail-under=29", 0),
    ((20, 30, 40, 50), None, "html --fail-under=31", 2),
    ((20, 30, 40, 50), None, "xml --fail-under=39", 0),
    ((20, 30, 40, 50), None, "xml --fail-under=41", 2),
    ((20, 30, 40, 50), None, "json --fail-under=49", 0),
    ((20, 30, 40, 50), None, "json --fail-under=51", 2),
    # Configuration file setting properly checks the result of reporting.
    ((20, 30, 40, 50), 19, "report", 0),
    ((20, 30, 40, 50), 21, "report", 2),
    ((20, 30, 40, 50), 29, "html", 0),
    ((20, 30, 40, 50), 31, "html", 2),
    ((20, 30, 40, 50), 39, "xml", 0),
    ((20, 30, 40, 50), 41, "xml", 2),
    ((20, 30, 40, 50), 49, "json", 0),
    ((20, 30, 40, 50), 51, "json", 2),
    # Command-line overrides configuration.
    ((20, 30, 40, 50), 19, "report --fail-under=21", 2),
])
def test_fail_under(results, fail_under, cmd, ret):
    cov = CoverageReportingFake(*results)
    if fail_under is not None:
        cov.set_option("report:fail_under", fail_under)
    with mock.patch("coverage.cmdline.Coverage", lambda *a,**kw: cov):
        ret_actual = command_line(cmd)
    assert ret_actual == ret
