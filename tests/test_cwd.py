import os
import subprocess
import sys

from shellac.shell import cwd_from_uri, read_proc_cwd

HOSTS = {"mybox"}


def test_plain_local_uri():
    assert cwd_from_uri("file:///home/chris/src", HOSTS) == "/home/chris/src"


def test_matching_hostname_is_accepted():
    assert cwd_from_uri("file://mybox/tmp", HOSTS) == "/tmp"
    assert cwd_from_uri("file://MyBox/tmp", HOSTS) == "/tmp"


def test_percent_encoding_is_decoded():
    assert cwd_from_uri("file://mybox/a%20b/caf%C3%A9", HOSTS) == "/a b/café"


def test_uri_from_another_host_is_ignored():
    # e.g. an ssh session whose remote shell emits OSC 7
    assert cwd_from_uri("file://server.example.org/srv/app", HOSTS) is None


def test_localhost_is_always_local():
    assert cwd_from_uri("file://localhost/tmp", HOSTS) == "/tmp"


def test_non_file_and_empty_uris_are_ignored():
    assert cwd_from_uri("https://example.org/x", HOSTS) is None
    assert cwd_from_uri("", HOSTS) is None
    assert cwd_from_uri(None, HOSTS) is None


def test_proc_cwd_of_a_real_process(tmp_path):
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], cwd=tmp_path)
    try:
        assert read_proc_cwd(child.pid) == str(tmp_path.resolve())
    finally:
        child.kill()
        child.wait()


def test_proc_cwd_of_missing_process_is_none():
    assert read_proc_cwd(None) is None
    assert read_proc_cwd(2**22 + os.getpid()) is None
