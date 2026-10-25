"""Unit tests for the Subversion error taxonomy."""

from src.infrastructure.vcs.svn_errors import (
    SvnAlreadyLockedError,
    SvnAuthError,
    SvnConflictError,
    SvnNetworkError,
    SvnOutOfDateError,
    SvnPathNotFoundError,
    SvnWorkingCopyLockedError,
    classify_svn_error,
    extract_error_code,
    extract_lock_owner,
)


def test_extract_error_code_prefers_first_stable_code():
    text = "svn: E170001: Authorization failed\nsvn: E200009: Some targets failed"
    assert extract_error_code(text) == "E170001"


def test_extract_lock_owner_quoted_and_unquoted():
    assert extract_lock_owner("Path '/x' is already locked by user 'ana'") == "ana"
    assert extract_lock_owner("Path '/x' is already locked by user ana") == "ana"


def test_classify_already_locked_carries_owner_and_path():
    error = classify_svn_error(
        "svn: warning: W160035: Path '/repo/a.blend' is already locked by user 'ana'"
    )
    assert isinstance(error, SvnAlreadyLockedError)
    assert error.owner == "ana"
    assert error.path == "/repo/a.blend"
    assert error.code == "W160035"


def test_classify_auth_network_and_working_copy_errors():
    assert isinstance(classify_svn_error("svn: E170001: Authorization failed"), SvnAuthError)
    assert isinstance(classify_svn_error("svn: E175002: Connection reset"), SvnNetworkError)
    assert isinstance(
        classify_svn_error("svn: E155004: Working copy locked"), SvnWorkingCopyLockedError
    )


def test_classify_out_of_date_conflict_and_missing_path():
    assert isinstance(
        classify_svn_error("svn: E160028: File is out of date"), SvnOutOfDateError
    )
    assert isinstance(classify_svn_error("svn: E155015: Conflict"), SvnConflictError)
    assert isinstance(
        classify_svn_error("svn: E160013: Path not found"), SvnPathNotFoundError
    )


def test_classify_prefers_already_locked_warning_over_generic_failure():
    text = (
        "svn: warning: W160035: Path '/repo/a.blend' is already locked by user 'ana'\n"
        "svn: E200009: Could not lock 'a.blend'"
    )
    error = classify_svn_error(text)
    assert isinstance(error, SvnAlreadyLockedError)
    assert error.owner == "ana"
    assert error.code == "W160035"
