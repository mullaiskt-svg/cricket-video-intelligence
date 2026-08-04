"""Unit tests for `cvip doctor` (orchestrator.run_doctor_checks() and its
CLI presentation). See specs/012-pipeline-orchestrator-cli/spec.md User
Story 5.

Note: `mocker.patch("importlib.import_module", ...)` must always be applied
LAST in each test -- `unittest.mock.patch("module.attr", ...)` resolves its
own dotted target via `importlib.import_module` internally, so patching
`importlib.import_module` *before* any other dotted-path patch silently
breaks that later patch's own target resolution (discovered directly while
writing these tests -- not an orchestrator.py bug).
"""

from cvip import cli, orchestrator


def test_run_doctor_checks_all_ok_when_everything_present(mocker):
    mocker.patch("shutil.which", return_value="/usr/bin/tool")
    mocker.patch("os.makedirs")
    mocker.patch("tempfile.NamedTemporaryFile", mocker.mock_open())
    mocker.patch("importlib.import_module")

    checks = orchestrator.run_doctor_checks()

    assert all(check.ok for check in checks)


def test_missing_ffmpeg_flagged_while_other_checks_still_run(mocker):
    def fake_which(binary):
        return None if binary == "ffmpeg" else "/usr/bin/tesseract"

    mocker.patch("shutil.which", side_effect=fake_which)
    mocker.patch("os.makedirs")
    mocker.patch("tempfile.NamedTemporaryFile", mocker.mock_open())
    mocker.patch("importlib.import_module")

    checks = orchestrator.run_doctor_checks()

    by_name = {c.name: c for c in checks}
    assert by_name["FFmpeg"].ok is False
    assert by_name["FFmpeg"].detail is not None
    assert by_name["Tesseract"].ok is True
    # Every other check still ran and reported its own independent result.
    assert by_name["Python"].ok is True


def test_python_version_check_reports_independently(mocker):
    mocker.patch("shutil.which", return_value="/usr/bin/tool")
    mocker.patch("os.makedirs")
    mocker.patch("tempfile.NamedTemporaryFile", mocker.mock_open())
    fake_sys = mocker.patch("cvip.orchestrator.sys")
    fake_sys.version_info = (3, 9, 0)
    fake_sys.version = "3.9.0"
    mocker.patch("importlib.import_module")

    checks = orchestrator.run_doctor_checks()
    by_name = {c.name: c for c in checks}
    assert by_name["Python"].ok is False


def test_package_importability_check_reports_independently(mocker):
    mocker.patch("shutil.which", return_value="/usr/bin/tool")
    mocker.patch("os.makedirs")
    mocker.patch("tempfile.NamedTemporaryFile", mocker.mock_open())

    def fake_import(name):
        if name == "pytesseract":
            raise ImportError("no module named pytesseract")
        return mocker.MagicMock()

    mocker.patch("importlib.import_module", side_effect=fake_import)

    checks = orchestrator.run_doctor_checks()
    by_name = {c.name: c for c in checks}
    assert by_name["pytesseract"].ok is False
    assert by_name["cv2"].ok is True


def test_directory_writability_check_reports_independently(mocker):
    mocker.patch("shutil.which", return_value="/usr/bin/tool")
    mocker.patch("tempfile.NamedTemporaryFile", mocker.mock_open())

    def fake_makedirs(directory, exist_ok=True):
        if directory == "output":
            raise OSError("permission denied")

    mocker.patch("os.makedirs", side_effect=fake_makedirs)
    mocker.patch("importlib.import_module")

    checks = orchestrator.run_doctor_checks()
    by_name = {c.name: c for c in checks}
    assert by_name["Output directory"].ok is False
    assert by_name["Data directory"].ok is True


def test_cli_doctor_prints_per_check_and_overall_status_exit_0(mocker, capsys):
    from cvip.orchestrator_models import DependencyCheckResult

    mocker.patch(
        "cvip.orchestrator.run_doctor_checks",
        return_value=(DependencyCheckResult(name="FFmpeg", ok=True), DependencyCheckResult(name="Tesseract", ok=True)),
    )

    exit_code = cli.main(["doctor"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "FFmpeg: OK" in output
    assert "Status: OK" in output


def test_cli_doctor_exit_1_when_any_check_fails(mocker, capsys):
    from cvip.orchestrator_models import DependencyCheckResult

    mocker.patch(
        "cvip.orchestrator.run_doctor_checks",
        return_value=(
            DependencyCheckResult(name="FFmpeg", ok=False, detail="not found"),
            DependencyCheckResult(name="Tesseract", ok=True),
        ),
    )

    exit_code = cli.main(["doctor"])

    assert exit_code == 1
    output = capsys.readouterr().out
    assert "FFmpeg: FAIL - not found" in output
    assert "Status: FAIL" in output
