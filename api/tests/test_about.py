def test_supported_sites_come_from_yt_dlp(harness):
    sites = harness.client.get("/sites").json()["sites"]

    assert "YouTube" in sites
    assert "generic" not in [s.lower() for s in sites]
    assert len(sites) > 500
    assert sites == sorted(sites, key=str.casefold)
    assert len(sites) == len({s.lower() for s in sites})


def test_about_reports_the_configured_contact_and_retention(make_harness):
    harness = make_harness(report_email="takedown@fetchall.example")

    assert harness.client.get("/about").json() == {
        "report_email": "takedown@fetchall.example",
        "log_retention_days": 7,
        "temp_file_minutes": 15,
    }


def test_about_without_a_contact(harness):
    assert harness.client.get("/about").json()["report_email"] is None
