"""Agency organizations: client grants, staff assignments, revocation, and onboarding.

Tests in this module share one scenario and run in file order. Revocation tests
come last because they remove access."""
import sqlite3
import uuid
from contextlib import closing

import pytest

from conftest import PASSWORD, build_business, headers, latest_code, ok, register
from test_tenant_isolation import REFUSED, database_fingerprint, foreign_record_requests, own_ids, resolve


@pytest.fixture(scope="module")
def agency(client):
    users = {name: register(client, f"{name}@agency-test.example", f"{name} home") for name in (
        "one_owner", "two_owner", "three_owner", "admin", "staff", "direct_staff", "outsider",
    )}
    clients = {}
    for key, owner, mark in (("one", "one_owner", "ONE-CLIENT"), ("two", "two_owner", "TWO-CLIENT"),
                             ("three", "three_owner", "THREE-CLIENT")):
        user = users[owner]
        clients[key] = build_business(client, user["token"], user["business_id"], mark, 250.0, 40)
    clients["three"]["invitation"] = ok(client.post(
        "/api/workspaces/invitations", headers=owner_headers(users, clients, "three"),
        json={"email": "three-invitee@agency-test.example", "role": "sales"}), 201)
    admin = headers(users["admin"]["token"])
    created = ok(client.post("/api/agencies", headers=admin, json={"name": "Growth Partners"}), 201)
    for name in ("staff", "direct_staff"):
        ok(client.post(f"/api/agencies/{created['id']}/members", headers=admin,
                       json={"email": f"{name}@agency-test.example", "role": "staff"}), 201)
    return {"users": users, "clients": clients, "agency": created}


def owner_headers(users, clients, key):
    return headers(users[f"{key}_owner"]["token"], clients[key]["business_id"])


def as_user(world, name, client_key=None):
    business = world["clients"][client_key]["business_id"] if client_key else None
    return headers(world["users"][name]["token"], business)


def agency_url(world, suffix=""):
    return f"/api/agencies/{world['agency']['id']}{suffix}"


def test_owner_previews_and_grants_access_with_agency_code(client, agency):
    code = agency["agency"]["access_code"]
    assert code and len(code.replace("-", "")) == 12
    one = owner_headers(agency["users"], agency["clients"], "one")
    preview = ok(client.post("/api/workspaces/agencies/preview", headers=one, json={"access_code": code.lower()}))
    assert preview == {"name": "Growth Partners", "already_granted": False}
    assert client.post("/api/workspaces/agencies/preview", headers=one,
                       json={"access_code": "WRONG-CODE-0000"}).status_code == 404
    grant = ok(client.post("/api/workspaces/agencies", headers=one,
                           json={"access_code": code, "role": "manager"}), 201)
    assert grant["agency_name"] == "Growth Partners" and grant["role"] == "manager"
    assert [person["email"] for person in grant["people"]] == ["admin@agency-test.example"]
    assert client.post("/api/workspaces/agencies", headers=one,
                       json={"access_code": code, "role": "manager"}).status_code == 409

    two = agency["clients"]["two"]
    grant = ok(client.post("/api/workspaces/agencies", headers=owner_headers(agency["users"], agency["clients"], "two"),
                           json={"access_code": code, "role": "website_editor", "website_ids": [two["site"]["id"]]}), 201)
    assert grant["website_ids"] == [two["site"]["id"]]


def test_only_direct_owners_control_agency_access(client, agency):
    code = agency["agency"]["access_code"]
    # The agency admin now manages client one but is not its owner.
    admin_in_one = as_user(agency, "admin", "one")
    for method, path, body in (
        ("GET", "/api/workspaces/agencies", None),
        ("POST", "/api/workspaces/agencies", {"access_code": code, "role": "manager"}),
        ("DELETE", f"/api/workspaces/agencies/{agency['agency']['id']}", None),
        ("GET", "/api/workspaces/members", None),
        ("POST", "/api/workspaces/invitations", {"email": "x@agency-test.example", "role": "manager"}),
    ):
        assert client.request(method, path, headers=admin_in_one, json=body).status_code == 403, path
    # Website editor scopes must name the client's own websites.
    three = owner_headers(agency["users"], agency["clients"], "three")
    response = client.post("/api/workspaces/agencies", headers=three, json={
        "access_code": code, "role": "website_editor", "website_ids": [agency["clients"]["one"]["site"]["id"]]})
    assert response.status_code == 422


def test_agency_admin_inherits_granted_roles_only(client, agency):
    workspaces = ok(client.get("/api/workspaces", headers=as_user(agency, "admin")))
    by_id = {workspace["id"]: workspace for workspace in workspaces}
    one, two, three = (agency["clients"][key] for key in ("one", "two", "three"))
    assert by_id[one["business_id"]]["role"] == "manager"
    assert by_id[one["business_id"]]["access"] == "agency"
    assert by_id[one["business_id"]]["agency_names"] == ["Growth Partners"]
    assert by_id[two["business_id"]]["role"] == "website_editor"
    assert three["business_id"] not in by_id

    assert "ONE-CLIENT" in client.get("/api/products", headers=as_user(agency, "admin", "one")).text
    assert client.get("/api/products", headers=as_user(agency, "admin", "three")).status_code == 403

    in_two = as_user(agency, "admin", "two")
    ok(client.get(f"/api/storefront?site_id={two['site']['id']}", headers=in_two))
    assert client.get(f"/api/storefront?site_id={two['second_site']['id']}", headers=in_two).status_code in REFUSED
    assert client.get("/api/customers", headers=in_two).status_code == 403


def test_unassigned_agency_staff_see_no_clients(client, agency):
    workspaces = ok(client.get("/api/workspaces", headers=as_user(agency, "staff")))
    assert [workspace["id"] for workspace in workspaces] == [agency["users"]["staff"]["business_id"]]
    assert ok(client.get(agency_url(agency, "/clients"), headers=as_user(agency, "staff"))) == []
    assert client.get("/api/products", headers=as_user(agency, "staff", "one")).status_code == 403
    assert client.get(agency_url(agency, "/members"), headers=as_user(agency, "staff")).status_code == 403


def test_staff_assignment_stays_within_client_grant(client, agency):
    admin = as_user(agency, "admin")
    staff_id = member_id(client, agency, "staff")
    one, two = agency["clients"]["one"]["business_id"], agency["clients"]["two"]["business_id"]
    assignment = ok(client.put(agency_url(agency, f"/clients/{one}/assignments/{staff_id}"), headers=admin,
                               json={"role": "sales"}))
    assert assignment["role"] == "sales"
    # Client two granted website editing only, so a manager assignment is refused.
    assert client.put(agency_url(agency, f"/clients/{two}/assignments/{staff_id}"), headers=admin,
                      json={"role": "manager"}).status_code == 422
    # Agency admins already inherit the grant; staff cannot assign anyone.
    admin_id = member_id(client, agency, "admin")
    assert client.put(agency_url(agency, f"/clients/{one}/assignments/{admin_id}"), headers=admin,
                      json={"role": "sales"}).status_code == 422
    assert client.put(agency_url(agency, f"/clients/{one}/assignments/{staff_id}"), headers=as_user(agency, "staff"),
                      json={"role": "manager"}).status_code == 403
    # Clients that did not grant access cannot be assigned.
    three = agency["clients"]["three"]["business_id"]
    assert client.put(agency_url(agency, f"/clients/{three}/assignments/{staff_id}"), headers=admin,
                      json={"role": "sales"}).status_code == 404

    staff_in_one = as_user(agency, "staff", "one")
    assert ok(client.get("/api/auth/me", headers=staff_in_one))["role"] == "sales"
    ok(client.get("/api/customers", headers=staff_in_one))
    assert client.get("/api/reports/sales", headers=staff_in_one).status_code == 403
    assert client.put(f"/api/products/{agency['clients']['one']['product']['id']}", headers=staff_in_one,
                      json={"name": "x", "price": 1, "stock": 1}).status_code == 403
    assert client.get("/api/products", headers=as_user(agency, "staff", "two")).status_code == 403
    clients = ok(client.get(agency_url(agency, "/clients"), headers=as_user(agency, "staff")))
    assert [(item["business_id"], item["your_role"], item["assignments"]) for item in clients] == [(one, "sales", None)]

    people = ok(client.get("/api/workspaces/agencies", headers=owner_headers(agency["users"], agency["clients"], "one")))
    assert {(p["email"], p["role"]) for p in people[0]["people"]} == {
        ("admin@agency-test.example", "manager"), ("staff@agency-test.example", "sales")}


def member_id(client, agency, name):
    members = ok(client.get(agency_url(agency, "/members"), headers=as_user(agency, "admin")))
    return next(member["id"] for member in members if member["email"] == f"{name}@agency-test.example")


def test_non_members_cannot_see_agency(client, agency):
    outsider = as_user(agency, "outsider")
    for path in ("", "/members", "/clients"):
        assert client.get(agency_url(agency, path), headers=outsider).status_code == 404
    assert ok(client.get("/api/agencies", headers=outsider)) == []
    # Staff see the agency but not its access code.
    assert ok(client.get(agency_url(agency), headers=as_user(agency, "staff")))["access_code"] is None


@pytest.mark.parametrize("attacker", ["admin", "staff"])
def test_agency_users_cannot_reach_ungranted_client_records(client, agency, attacker):
    """Working inside granted client one, agency users target client three's IDs."""
    one, three = agency["clients"]["one"], agency["clients"]["three"]
    before = database_fingerprint(client)
    failures = []
    h = as_user(agency, attacker, "one")
    for method, path, body in foreign_record_requests(three):
        path, body = resolve(path, own_ids(one)), resolve(body, own_ids(one))
        response = client.request(method, path, headers=h, json=body)
        if response.status_code not in REFUSED or "THREE-CLIENT" in response.text:
            failures.append((method, path, response.status_code))
    assert not failures
    assert database_fingerprint(client) == before


def test_narrowing_a_grant_narrows_staff_assignments(client, agency):
    three = owner_headers(agency["users"], agency["clients"], "three")
    business = agency["clients"]["three"]["business_id"]
    ok(client.post("/api/workspaces/agencies", headers=three,
                   json={"access_code": agency["agency"]["access_code"], "role": "manager"}), 201)
    admin = as_user(agency, "admin")
    staff_id, direct_id = member_id(client, agency, "staff"), member_id(client, agency, "direct_staff")
    ok(client.put(agency_url(agency, f"/clients/{business}/assignments/{staff_id}"), headers=admin, json={"role": "manager"}))
    ok(client.put(agency_url(agency, f"/clients/{business}/assignments/{direct_id}"), headers=admin,
                  json={"role": "website_editor"}))
    ok(client.put(f"/api/workspaces/agencies/{agency['agency']['id']}", headers=three, json={"role": "sales"}))
    assert ok(client.get("/api/auth/me", headers=as_user(agency, "staff", "three")))["role"] == "sales"
    assert client.get("/api/auth/me", headers=as_user(agency, "direct_staff", "three")).status_code == 403
    assert ok(client.get("/api/auth/me", headers=as_user(agency, "admin", "three")))["role"] == "sales"
    ok(client.delete(f"/api/workspaces/agencies/{agency['agency']['id']}", headers=three), 204)


def test_revocation_is_immediate_and_preserves_direct_membership(client, agency):
    users, clients = agency["users"], agency["clients"]
    one = clients["one"]["business_id"]
    owner = owner_headers(users, clients, "one")
    admin = as_user(agency, "admin")
    direct_id = member_id(client, agency, "direct_staff")
    # direct_staff is a direct sales member of client one and also an agency manager there.
    ok(client.post("/api/workspaces/members", headers=owner,
                   json={"email": "direct_staff@agency-test.example", "role": "sales"}), 201)
    ok(client.put(agency_url(agency, f"/clients/{one}/assignments/{direct_id}"), headers=admin, json={"role": "manager"}))
    me = ok(client.get("/api/auth/me", headers=as_user(agency, "direct_staff", "one")))
    assert (me["role"], me["access"]) == ("manager", "agency")
    ok(client.get("/api/reports/sales", headers=as_user(agency, "direct_staff", "one")))

    ok(client.delete(f"/api/workspaces/agencies/{agency['agency']['id']}", headers=owner), 204)

    # Existing sessions lose inherited access on their next request.
    for name in ("admin", "staff"):
        assert client.get("/api/products", headers=as_user(agency, name, "one")).status_code == 403
        assert one not in [w["id"] for w in ok(client.get("/api/workspaces", headers=as_user(agency, name)))]
    me = ok(client.get("/api/auth/me", headers=as_user(agency, "direct_staff", "one")))
    assert (me["role"], me["access"], me["agency_names"]) == ("sales", "direct", [])
    ok(client.get("/api/customers", headers=as_user(agency, "direct_staff", "one")))
    assert client.get("/api/reports/sales", headers=as_user(agency, "direct_staff", "one")).status_code == 403
    with closing(sqlite3.connect(client.database_path)) as db:
        assert db.execute("SELECT COUNT(*) FROM agency_client_assignments WHERE business_id = ?", (one,)).fetchone()[0] == 0
    assert all(item["business_id"] != one for item in ok(client.get(agency_url(agency, "/clients"), headers=admin)))
    events = ok(client.get("/api/workspaces/activity", headers=owner))["events"]
    assert any(event["action"] == "Agency access revoked" for event in events)


def test_removing_agency_member_removes_inherited_access(client, agency):
    two = agency["clients"]["two"]["business_id"]
    admin = as_user(agency, "admin")
    staff_id = member_id(client, agency, "staff")
    ok(client.put(agency_url(agency, f"/clients/{two}/assignments/{staff_id}"), headers=admin,
                  json={"role": "website_editor"}))
    ok(client.get("/api/auth/me", headers=as_user(agency, "staff", "two")))
    ok(client.delete(agency_url(agency, f"/members/{staff_id}"), headers=admin), 204)
    assert client.get("/api/auth/me", headers=as_user(agency, "staff", "two")).status_code == 403
    assert client.get(agency_url(agency), headers=as_user(agency, "staff")).status_code == 404
    admin_id = member_id(client, agency, "admin")
    assert client.delete(agency_url(agency, f"/members/{admin_id}"), headers=admin).status_code == 409


def test_agency_onboarding_hands_ownership_to_client(client, agency):
    admin = as_user(agency, "admin")
    created = ok(client.post(agency_url(agency, "/clients"), headers=admin, json={
        "business_name": "New Client Stores", "owner_email": "new-client@agency-test.example"}), 201)
    business = created["business_id"]
    assert created["invitation"]["role"] == "owner"

    # During onboarding: no owner, the agency manages the workspace, and it cannot withdraw.
    in_new = headers(agency["users"]["admin"]["token"], business)
    assert ok(client.get("/api/auth/me", headers=in_new))["role"] == "manager"
    ok(client.post("/api/products", headers=in_new, json={"name": "Starter item", "price": 10, "stock": 3}), 201)
    status = next(c for c in ok(client.get(agency_url(agency, "/clients"), headers=admin)) if c["business_id"] == business)
    assert (status["owner_status"], status["pending_owner_email"], status["created_by_agency"]) == (
        "invitation_pending", "new-client@agency-test.example", True)
    assert client.delete(agency_url(agency, f"/clients/{business}"), headers=admin).status_code == 409
    assert client.get("/api/workspaces/members", headers=in_new).status_code == 403
    assert client.post(agency_url(agency, f"/clients/{business}/owner-invitation"), headers=as_user(agency, "outsider"),
                       json={"email": "attacker@agency-test.example"}).status_code == 404

    # A reissued invitation replaces the earlier link.
    reissued = ok(client.post(agency_url(agency, f"/clients/{business}/owner-invitation"), headers=admin,
                              json={"email": "new-client@agency-test.example"}), 201)
    assert client.post("/api/auth/invitations/preview",
                       json={"token": created["invitation"]["token"]}).status_code == 404
    preview = ok(client.post("/api/auth/invitations/preview", json={"token": reissued["token"]}))
    assert (preview["role"], preview["business_name"]) == ("owner", "New Client Stores")
    assert preview["verification_required"] is True
    # A new account must prove it controls the invited email.
    assert client.post("/api/auth/invitations/accept",
                       json={"token": reissued["token"], "password": PASSWORD}).status_code == 422
    ok(client.post("/api/auth/invitations/send-code", json={"token": reissued["token"]}), 202)
    owner = ok(client.post("/api/auth/invitations/accept", json={
        "token": reissued["token"], "password": PASSWORD, "code": latest_code("new-client@agency-test.example")}))
    assert (owner["role"], owner["business_id"]) == ("owner", business)

    # After onboarding: the client owns the workspace and controls agency access.
    owner_h = headers(owner["token"], business)
    grants = ok(client.get("/api/workspaces/agencies", headers=owner_h))
    assert [(g["agency_name"], g["role"], g["created_client"]) for g in grants] == [("Growth Partners", "manager", True)]
    assert client.post(agency_url(agency, f"/clients/{business}/owner-invitation"), headers=admin,
                       json={"email": "second-owner@agency-test.example"}).status_code == 409
    ok(client.delete(f"/api/workspaces/agencies/{agency['agency']['id']}", headers=owner_h), 204)
    assert client.get("/api/products", headers=in_new).status_code == 403
    assert "Starter item" in client.get("/api/products", headers=owner_h).text


def test_assignments_outside_the_grant_are_ignored_at_read_time(client, agency):
    """Backstop for assignments written outside the API: an assignment that does not
    fit the client's grant gives no access, even if it is stored."""
    two = agency["clients"]["two"]["business_id"]  # Granted website editing only.
    with closing(sqlite3.connect(client.database_path)) as db, db:
        user_id, = db.execute("SELECT id FROM users WHERE email = 'direct_staff@agency-test.example'").fetchone()
        db.execute("""
            INSERT INTO agency_client_assignments (agency_id, business_id, user_id, role, assigned_by, assigned_at)
            VALUES (?, ?, ?, 'manager', 'test', 'test')
        """, (agency["agency"]["id"], two, user_id))
    try:
        assert client.get("/api/auth/me", headers=as_user(agency, "direct_staff", "two")).status_code == 403
    finally:
        with closing(sqlite3.connect(client.database_path)) as db, db:
            db.execute("DELETE FROM agency_client_assignments WHERE business_id = ? AND user_id = ?", (two, user_id))


def test_owner_invitation_cannot_be_accepted_once_an_owner_exists(client, agency):
    """Backstop for concurrent onboarding: a stale owner invitation for a business
    that already has an owner is refused at acceptance."""
    from auth import token_hash
    token = "A" * 43
    business = agency["clients"]["three"]["business_id"]
    with closing(sqlite3.connect(client.database_path)) as db, db:
        db.execute("""
            INSERT INTO workspace_invitations (business_id, email, role, token_hash, expires_at)
            VALUES (?, 'late-owner@agency-test.example', 'owner', ?, strftime('%s', 'now') + 3600)
        """, (business, token_hash(token)))
    ok(client.post("/api/auth/invitations/send-code", json={"token": token}), 202)
    response = client.post("/api/auth/invitations/accept", json={
        "token": token, "password": PASSWORD, "code": latest_code("late-owner@agency-test.example")})
    assert response.status_code == 409
    with closing(sqlite3.connect(client.database_path)) as db:
        owners = db.execute("SELECT COUNT(*) FROM business_memberships WHERE business_id = ? AND role = 'owner'",
                            (business,)).fetchone()[0]
        assert owners == 1
        assert db.execute("SELECT 1 FROM users WHERE email = 'late-owner@agency-test.example'").fetchone() is None
