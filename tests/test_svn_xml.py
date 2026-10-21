"""Unit tests for the Subversion XML parsers."""

from src.infrastructure.vcs.svn_xml import parse_info_xml, parse_status_xml


STATUS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<status>
<target path="/project/svn">
  <entry path="/project/svn/pro/a.blend">
    <wc-status item="modified" props="none" revision="7" tree-conflicted="false">
      <commit revision="7"><author>ana</author></commit>
    </wc-status>
    <repos-status item="none" props="none"/>
  </entry>
  <entry path="/project/svn/pro/new.png">
    <wc-status item="unversioned" props="none" tree-conflicted="false"/>
  </entry>
  <entry path="/project/svn/pro/conflict.blend">
    <wc-status item="conflicted" props="none" revision="7" tree-conflicted="true">
      <lock><token>abc</token><owner>ana</owner><comment>editing</comment></lock>
    </wc-status>
  </entry>
</target>
</status>
"""


INFO_XML = """<?xml version="1.0" encoding="UTF-8"?>
<info>
<entry kind="file" path="/project/svn/pro/a.blend" revision="8">
  <url>svn://server/project/svn/pro/a.blend</url>
  <relative-url>^/pro/a.blend</relative-url>
  <repository><root>svn://server/project</root><uuid>abc-123</uuid></repository>
  <wc-info><wcroot-abspath>/project/svn</wcroot-abspath></wc-info>
  <commit revision="8"><author>ana</author></commit>
  <lock><token>token-1</token><owner>ana</owner><comment>editing</comment></lock>
</entry>
</info>
"""


def test_parse_status_xml_reports_changes_untracked_and_tree_conflicts():
    entries = {entry.path.rsplit("/", 1)[-1]: entry for entry in parse_status_xml(STATUS_XML)}

    assert entries["a.blend"].item == "modified"
    assert entries["a.blend"].is_modified is True
    assert entries["new.png"].is_unversioned is True
    assert entries["conflict.blend"].is_conflicted is True
    assert entries["conflict.blend"].lock.owner == "ana"


def test_parse_info_xml_returns_url_and_lock():
    info = parse_info_xml(INFO_XML)

    assert info.url == "svn://server/project/svn/pro/a.blend"
    assert info.repository_root == "svn://server/project"
    assert info.wc_root == "/project/svn"
    assert info.lock.owner == "ana"
    assert info.lock.token == "token-1"
