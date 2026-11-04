import io


def test_health(client):
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/ready").status_code == 200


def test_auth_flow_and_rbac(client, admin):
    r = client.post("/api/auth/register", json={"email": "rev@example.com", "name": "Rev", "password": "password123"})
    assert r.json()["user"]["role"] == "analyst"  # only the first user becomes admin
    uid = r.json()["user"]["id"]
    assert client.patch(f"/api/users/{uid}/role", json={"role": "reviewer"}, headers=admin).status_code == 200
    login = client.post("/api/auth/login", data={"username": "rev@example.com", "password": "password123"})
    rev = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert client.get("/api/auth/me", headers=rev).json()["role"] == "reviewer"
    # reviewers cannot create projects
    assert client.post("/api/projects", json={"name": "x"}, headers=rev).status_code == 403
    assert client.get("/api/projects").status_code == 401
    assert client.post("/api/auth/login", data={"username": "rev@example.com", "password": "wrong"}).status_code == 401


def test_generation_builds_connected_blueprint(client, admin, project):
    dash = client.get(f"/api/projects/{project}/dashboard", headers=admin).json()
    for t in ("requirement", "story", "module", "api", "entity", "test", "risk"):
        assert dash["by_type"].get(t, {}).get("total", 0) > 0, t
    q = dash["quality"]
    assert 0 <= q["score"] <= 100
    assert q["coverage"] == 100.0  # self-check repaired every structural gap
    rows = client.get(f"/api/projects/{project}/trace", headers=admin).json()
    for row in rows:
        assert row["tests"], row
        if row["kind"] == "FR":
            assert row["storys"] and row["modules"], row


def test_checker_finds_duplicate_contradiction_and_vague(client, admin, project):
    kinds = {f["kind"] for f in client.get(f"/api/projects/{project}/findings", headers=admin).json()}
    assert {"duplicate", "contradiction", "vague_term"} <= kinds, kinds


def test_change_impact_propagation(client, admin, project):
    items = client.get(f"/api/projects/{project}/items?type=requirement", headers=admin).json()
    req = next(i for i in items if "pay" in i["title"].lower())
    preview = client.get(f"/api/items/{req['id']}/impact", headers=admin).json()
    assert preview, "requirement should have dependents"
    r = client.patch(f"/api/items/{req['id']}", json={"description": "Students must pay via UPI or card.", "change_note": "card"}, headers=admin)
    body = r.json()
    assert body["item"]["version"] == 2
    assert {i["key"] for i in body["impacted"]} == {i["key"] for i in preview}
    stale = client.get(f"/api/projects/{project}/items?stale=true", headers=admin).json()
    assert {s["key"] for s in stale} >= {i["key"] for i in preview}
    assert len(client.get(f"/api/items/{req['id']}/versions", headers=admin).json()) == 1  # v2 snapshot
    # status-only change does not bump version or propagate
    r2 = client.patch(f"/api/items/{req['id']}", json={"status": "in_progress"}, headers=admin).json()
    assert r2["item"]["version"] == 2 and r2["impacted"] == []


def test_baseline_and_diff(client, admin, project):
    b = client.post(f"/api/projects/{project}/baselines", json={"note": "v1"}, headers=admin)
    assert b.status_code == 201 and b.json()["version"] == 1
    story = client.get(f"/api/projects/{project}/items?type=story", headers=admin).json()[0]
    client.patch(f"/api/items/{story['id']}", json={"title": story["title"] + " quickly"}, headers=admin)
    d = client.get(f"/api/projects/{project}/diff", headers=admin).json()
    assert story["key"] in d["changed"]


def test_exports(client, admin, project):
    for fmt, magic in (("pdf", b"%PDF"), ("docx", b"PK"), ("csv", b"key,type"), ("json", b"{"), ("jira", b"Summary"), ("github", b"[")):
        r = client.get(f"/api/projects/{project}/export/{fmt}", headers=admin)
        assert r.status_code == 200 and r.content.startswith(magic), fmt


def test_upload_docx_brief_and_similarity(client, admin, project):
    import docx

    d = docx.Document()
    d.add_paragraph("Patients must be able to book an appointment with a doctor.")
    d.add_paragraph("Doctors can view their daily appointment schedule.")
    buf = io.BytesIO()
    d.save(buf)
    pid = client.post("/api/projects", json={"name": "Clinic"}, headers=admin).json()["id"]
    r = client.post(f"/api/projects/{pid}/brief", files={"file": ("brief.docx", buf.getvalue(), "application/octet-stream")}, headers=admin)
    assert r.status_code == 200 and "appointment" in r.json()["brief_text"]
    bad = client.post(f"/api/projects/{pid}/brief", files={"file": ("x.exe", b"MZ", "application/octet-stream")}, headers=admin)
    assert bad.status_code == 415
    sim = client.get(f"/api/projects/{project}/similar", params={"q": "login with college email"}, headers=admin).json()
    assert sim and sim[0]["similarity"] > 0.3


def test_manual_item_and_links(client, admin, project):
    req = client.post(f"/api/projects/{project}/items", json={"type": "requirement", "title": "Staff can mark an item as sold out"}, headers=admin).json()
    assert req["key"].startswith("REQ-") and req["data"]["kind"] == "FR"
    t = client.post(f"/api/projects/{project}/items", json={"type": "test", "title": "Sold-out item hidden", "link_from": [req["id"]]}, headers=admin).json()
    links = client.get(f"/api/items/{req['id']}/links", headers=admin).json()
    assert links["downstream"][0]["key"] == t["key"]


def test_self_check_repairs_missing_coverage(client, admin, project):
    req = client.post(f"/api/projects/{project}/items", json={"type": "requirement", "title": "Students can save favourite dishes"}, headers=admin).json()
    job = client.post(f"/api/projects/{project}/check", headers=admin).json()
    job = client.get(f"/api/jobs/{job['id']}", headers=admin).json()
    assert job["status"] == "succeeded"
    assert job["result"]["quality"]["auto_repaired"] >= 2  # story + test (+ module link)
    links = client.get(f"/api/items/{req['id']}/links", headers=admin).json()["downstream"]
    assert {"story", "test"} <= {l["type"] for l in links}
    assert {i["origin"] for i in client.get(f"/api/projects/{project}/items?type=test", headers=admin).json()} >= {"repaired"}


def test_prometheus_metrics(client, admin, project):
    client.get(f"/api/projects/{project}/export/csv", headers=admin)
    body = client.get("/metrics").text
    for name in ("specforge_http_requests_total", "specforge_http_request_duration_seconds_bucket", "specforge_jobs{",
                 "specforge_blueprint_quality_score{", "specforge_exports_total{format=\"csv\"}", "specforge_database_up 1.0", "specforge_build_info{"):
        assert name in body, name
    assert 'route="/api/projects/{project_id}/export/{fmt}"' in body  # templated route, not raw path


def test_github_issues_export(client, admin, project):
    import json

    issues = json.loads(client.get(f"/api/projects/{project}/export/github", headers=admin).content)
    assert issues and all({"title", "body", "labels"} <= set(i) for i in issues)
    assert any("user-story" in i["labels"] for i in issues) and any("test" in i["labels"] for i in issues)
