"""Unit tests for the report error exception hierarchy.

Tests that the custom exception classes carry the correct attributes,
follow the inheritance hierarchy, and format messages properly.

Requirements: 14.1, 14.2, 14.3, 14.4
"""

import pytest

from services.report_errors import (
    ReportError,
    ReportRenderError,
    ReportUploadError,
    ReportValidationError,
)


class TestReportError:
    """Tests for the base ReportError exception."""

    def test_stores_report_id(self):
        """ReportError carries the report_id attribute."""
        err = ReportError("abc-123", "something broke")
        assert err.report_id == "abc-123"

    def test_stores_message(self):
        """ReportError carries a descriptive message."""
        err = ReportError("abc-123", "something broke")
        assert err.message == "something broke"

    def test_str_includes_report_id_and_message(self):
        """String representation includes report_id in brackets."""
        err = ReportError("rpt-456", "render failed")
        assert str(err) == "[rpt-456] render failed"

    def test_is_exception(self):
        """ReportError inherits from Exception."""
        err = ReportError("id", "msg")
        assert isinstance(err, Exception)

    def test_can_be_raised_and_caught(self):
        """ReportError can be raised and caught as Exception."""
        with pytest.raises(ReportError) as exc_info:
            raise ReportError("r-1", "test error")
        assert exc_info.value.report_id == "r-1"


class TestReportValidationError:
    """Tests for ReportValidationError exception."""

    def test_inherits_from_report_error(self):
        """ReportValidationError is a subclass of ReportError."""
        err = ReportValidationError("id", "validation failed")
        assert isinstance(err, ReportError)

    def test_stores_invalid_fields_with_reasons(self):
        """ReportValidationError carries field names with reasons."""
        fields = [
            {"field": "overall_score", "reason": "must be between 0.0 and 10.0"},
            {"field": "dimensions", "reason": "must contain exactly 7 entries"},
        ]
        err = ReportValidationError("rpt-1", "validation failed", invalid_fields=fields)
        assert err.invalid_fields == fields
        assert len(err.invalid_fields) == 2

    def test_invalid_fields_defaults_to_empty_list(self):
        """invalid_fields defaults to empty list when not provided."""
        err = ReportValidationError("rpt-1", "validation failed")
        assert err.invalid_fields == []

    def test_preserves_report_id_and_message(self):
        """Inherits report_id and message from base class."""
        err = ReportValidationError("rpt-val-1", "bad data")
        assert err.report_id == "rpt-val-1"
        assert err.message == "bad data"

    def test_str_format(self):
        """String representation follows base class format."""
        err = ReportValidationError("rpt-val-2", "invalid scores")
        assert str(err) == "[rpt-val-2] invalid scores"


class TestReportRenderError:
    """Tests for ReportRenderError exception."""

    def test_inherits_from_report_error(self):
        """ReportRenderError is a subclass of ReportError."""
        err = ReportRenderError("id", "render failed")
        assert isinstance(err, ReportError)

    def test_stores_template_path(self):
        """ReportRenderError carries the template_path attribute."""
        err = ReportRenderError(
            "rpt-2",
            "template not found",
            template_path="templates/coaching_report.html",
        )
        assert err.template_path == "templates/coaching_report.html"

    def test_stores_details(self):
        """ReportRenderError carries additional error details."""
        err = ReportRenderError(
            "rpt-3",
            "WeasyPrint failed",
            details="cairo surface creation error at line 42",
        )
        assert err.details == "cairo surface creation error at line 42"

    def test_template_path_defaults_to_none(self):
        """template_path defaults to None when not provided."""
        err = ReportRenderError("rpt-4", "render error")
        assert err.template_path is None

    def test_details_defaults_to_none(self):
        """details defaults to None when not provided."""
        err = ReportRenderError("rpt-5", "render error")
        assert err.details is None

    def test_preserves_report_id_and_message(self):
        """Inherits report_id and message from base class."""
        err = ReportRenderError("rpt-r-1", "Jinja2 syntax error")
        assert err.report_id == "rpt-r-1"
        assert err.message == "Jinja2 syntax error"


class TestReportUploadError:
    """Tests for ReportUploadError exception."""

    def test_inherits_from_report_error(self):
        """ReportUploadError is a subclass of ReportError."""
        err = ReportUploadError("id", "upload failed")
        assert isinstance(err, ReportError)

    def test_preserves_report_id_and_message(self):
        """Inherits report_id and message from base class."""
        err = ReportUploadError("rpt-u-1", "S3 throttled after 3 retries")
        assert err.report_id == "rpt-u-1"
        assert err.message == "S3 throttled after 3 retries"

    def test_str_format(self):
        """String representation follows base class format."""
        err = ReportUploadError("rpt-u-2", "access denied")
        assert str(err) == "[rpt-u-2] access denied"


class TestExceptionHierarchy:
    """Tests verifying the inheritance structure of the hierarchy."""

    def test_all_subclasses_catchable_as_report_error(self):
        """All exception types can be caught with except ReportError."""
        exceptions = [
            ReportValidationError("1", "val"),
            ReportRenderError("2", "render"),
            ReportUploadError("3", "upload"),
        ]
        for exc in exceptions:
            with pytest.raises(ReportError):
                raise exc

    def test_subclasses_catchable_as_exception(self):
        """All exception types can be caught with except Exception."""
        exceptions = [
            ReportError("0", "base"),
            ReportValidationError("1", "val"),
            ReportRenderError("2", "render"),
            ReportUploadError("3", "upload"),
        ]
        for exc in exceptions:
            with pytest.raises(Exception):
                raise exc
