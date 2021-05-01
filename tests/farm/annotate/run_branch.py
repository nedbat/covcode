# Licensed under the Apache License: http://www.apache.org/licenses/LICENSE-2.0
# For details: https://bitbucket.org/ned/coveragepy/src/default/NOTICE.txt

from tests.test_farm import clean, compare, copy, run

copy("src", "out")
run("""
    coverage run --branch white.py
    coverage annotate white.py
    """, rundir="out")
compare("out", "gold_branch", "*,cover")
clean("out")
