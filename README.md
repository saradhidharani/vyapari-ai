# Vyapari AI — Starter Application

A **local demo foundation** for a multilingual AI Business Manager SaaS. Not production-ready.

## Included
- Responsive React dashboard with sidebar navigation
- Products list with add, edit, and delete actions backed by SQLite
- Local sign-in, business switching, and owner-managed access for existing accounts
- Read-only platform admin directory
- Customers list with add, edit, and delete actions backed by SQLite
- Business-scoped orders with multiple products, stock deductions, and manual payment status
- Sales analytics with date filters for recorded payments and refunds
- Multiple websites per business, each with its own draft and local read-only link
- Assistant with predefined read-only business queries and saved conversation history
- FastAPI with `/health`, `/docs`, `/api/products`, `/api/customers`, and `/api/orders`
- `CLAUDE.md` with project requirements and guardrails for Claude Code

## Requirements
- Node.js 20+ (Node 22 recommended)
- Python 3.11+
- Windows PowerShell and VS Code

## Frontend
In a terminal opened at the project root:

```powershell
cd frontend
npm.cmd install
npm.cmd run dev
```

Open http://localhost:5173

If npm permissions fail under `C:\Users`, move/extract the project to a user-owned folder such as `Documents\Projects` and reopen VS Code there. `npm.cmd` avoids PowerShell's npm.ps1 execution-policy error.

## Backend
In a **second** PowerShell terminal opened at the project root:

```powershell
cd backend
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn main:app --reload --port 8000
```

Open http://127.0.0.1:8000/docs or http://127.0.0.1:8000/health

Use **Settings → Check connection** in the frontend to test the backend.

### Email setup, sign-up, and sign-in

Sign-up, the code step for existing accounts, password reset, and invitation acceptance send 6-digit codes by email. Set these environment variables in the PowerShell session before starting FastAPI. Keep credentials out of the repository.

| Variable | Purpose |
| --- | --- |
| `VYAPARI_SECRET_KEY` | At least 32 random characters. Codes and rate-limit records are keyed with it. Required in production. Without it, a temporary key is used and outstanding codes stop working when the server restarts. |
| `VYAPARI_EMAIL_PROVIDER` | `brevo` sends through Brevo's HTTPS email API. Use it on hosts that block SMTP, such as Railway's Trial and Hobby plans. It needs `VYAPARI_BREVO_API_KEY` and a `VYAPARI_EMAIL_FROM` address that is a verified sender in Brevo. `smtp` for real email through a mail server. `dev_file` writes messages to `VYAPARI_DEV_OUTBOX` for local testing only. `fake` is for automated tests only. Unset means code requests fail with "Email delivery is not configured". |
| `VYAPARI_SMTP_HOST`, `VYAPARI_SMTP_PORT` (default `587`), `VYAPARI_SMTP_USERNAME`, `VYAPARI_SMTP_PASSWORD`, `VYAPARI_EMAIL_FROM` | Your mailbox or email service's SMTP settings. `VYAPARI_SMTP_SECURITY` is `starttls` (default) or `ssl`. |
| `VYAPARI_ENV` | Set to `production` on the public server. Startup then fails unless SMTP and a secret key are configured, and the `fake` and `dev_file` providers are refused. |

For local testing without real email:

```powershell
$env:VYAPARI_EMAIL_PROVIDER = "dev_file"
$env:VYAPARI_DEV_OUTBOX = "C:\path\to\private\vyapari-outbox.jsonl"
```

Choose **Create a business account**, enter your email, and select **Send code**. Enter the 6-digit code from the email, then choose a business name and password. Codes expire after 10 minutes, work once, and are cancelled after 5 incorrect attempts or when a new code is sent. Each email address can receive one code per minute and five per hour. Failed codes and failed sign-ins are also limited. The app shows when to try again.

Sign in with a verified email and password. Select **Forgot password?** to reset it with a code sent to the account's email. A reset signs out every other session.

Accounts created before verification keep their businesses, records, and memberships. They cannot use the app until their email is verified, including through a session that was already open. On the next sign-in with the correct password, a code is sent to the account email; entering it verifies the account. A password reset also verifies the email. For fictional local demo accounts that cannot receive email, an operator can run `.\.venv\Scripts\python.exe -m platform_admin verify-email owner@example.com` from `backend`. Use it only when you know the person controls the address.

Open **Products** after signing in. The first local business account receives products saved before sign-in was added. Each subsequent business starts with an empty catalog. Use **Settings → Sign out** to switch accounts.

Set a **Low-stock threshold** when adding or editing a product. Products and the assistant flag stock below that product's threshold. Owners and managers can select **Stock** beside a product to add or remove units with a reason and review stock movements from adjustments, product edits, orders, cancellations, and restocked refunds. Movement history starts with this update.

Set optional **Target stock** to plan a larger refill. **Products → Restock list** shows items below their threshold and the units needed to reach target stock. If a target is blank, the threshold is used as the target. **Export restock CSV** saves the list for ordering.

Owners and managers can use **Purchasing** to save supplier contacts and record purchase orders. **Receive all** adds the full delivery to stock and records the movement for each product. Cancel an open order when the delivery is no longer expected.

Use **Settings → Create another business** to open a separate workspace with your current login. Choose a business from the sidebar to switch workspaces. In **Settings → Team access**, owners can add an existing Vyapari account as **Sales staff**, **Website editor**, or **Manager**, change its role, or remove its access. A member can refresh their workspace list in **Settings** after access is granted or reload the app after a role change.

Sales staff can view products, add and update customers, create orders, record payments, and cancel pending orders. Managers and owners can also edit inventory, delete customer records, handle refunds, view reports, use the assistant, and manage websites. Team access is restricted to owners.

Website editors can update their assigned website drafts and choose products by name and price. In **Settings → Team access**, owners can select **Website access** for an editor and assign individual websites or grant access to all current and future websites. New editors start with no assigned websites. Existing editors keep their previous access until an owner changes it. Owners and managers create, publish, or take down websites. Customer, order, stock, and report endpoints require separate business permissions.

Owners can review the **Activity log** in **Settings**. It records who changed team access, recorded payments or refunds, cancelled orders, published or took down websites, or decided a website request. The log records actions from this update onward.

### Agencies

An agency manages several client businesses from one login. Open **Agencies** and create an agency. The creator becomes an **Agency admin**. Admins can add existing Vyapari accounts as **Agency admin** or **Agency staff**. The agency page shows its access code to admins.

A client business owner grants access in **Settings → Agency access**. The owner enters the agency's access code, checks the agency name, and chooses the agency's highest role: **Manager**, **Sales staff**, or **Website editor**. Website editor access can cover all websites or selected websites. The panel lists everyone who can reach the business through the agency. Owners can change or revoke access at any time. Revoking takes effect on the next request. People the owner added directly under **Team access** keep their own access.

Agency admins work in every client at the role the client granted. Agency staff see only clients an admin assigned to them, at a role within the client's grant. Lowering a grant also lowers or removes staff assignments above it. Removing someone from the agency removes their agency access to every client. Agencies never hold the owner role, so they cannot manage a client's team, invitations, activity log, or agency access. Assignments and grant changes appear in the client's activity log.

An agency admin can choose **Create client workspace** with the client's email. The new workspace has no owner yet. The agency has manager access, and the admin shares the owner invitation link with the client. The admin can create a new link while the invitation is pending. The agency cannot withdraw from a workspace that has no owner. When the client accepts, they become its only owner and control agency access. The agency can then no longer invite owners and may withdraw.

The **Client dashboard** at the top of the Agencies page lists clients you can reach through the selected agency. Each client shows your role, website count, and an **Open workspace** action. Website counts include active sites only, and website editors see only their assigned sites. Sales staff have no website access, so their count shows "—". Choose a **Date range** to see each client's payments, refunds, and net sales in INR, plus a combined total. The ranges match **Analytics** and use India Standard Time. The server checks reporting permission separately for each client on every request. Clients where your role cannot view reports show **No report access** and are left out of the combined total. Direct workspace memberships, other agencies' clients, unassigned clients, and revoked clients are never included. Select **Refresh** to load the latest access and sales.

Select **Open workspace** on the Agencies page or use the sidebar business menu. Workspaces reached through an agency are labelled with the agency name. When someone has both direct and agency access, the higher role applies. Sales staff and Website editor are different permissions, so if the two routes give those two roles, the direct membership is kept.

Use **Settings → Invite staff** to create a seven-day, single-use invitation for a Sales staff, Website editor, or Manager role. Copy and privately share the link. Staff can join the business without creating a workspace. Only the invited email address can accept. Invitees with a verified account enter their current password. New staff choose a password and enter a code sent to the invited email. Existing accounts that have not verified their email enter both their password and the code. Accepting opens the invited business with the invited role. An owner can revoke an unused invitation or create a replacement link for the same email. Links use the address of the running app, so a localhost link can be tested on the same computer.

To grant the platform admin directory to an existing account, run this from the project root in the local PowerShell terminal, replacing the example email:

```powershell
cd backend
.\.venv\Scripts\python.exe -m platform_admin grant owner@example.com
```

Refresh the app after granting access. **Platform admin** shows all businesses, their owners, team sizes, and total and published website counts. Access to a business's records still requires a membership. Use the same command with `revoke` to remove platform access.

## Tenant isolation and authentication tests

Run the cross-business isolation tests from `backend`:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest tests -q
```

The tests create two fictional businesses in a temporary SQLite file. They never open `backend/vyapari.db`. Accounts include owners, an agency manager with access to both businesses, a website editor assigned to one site, and sales staff. Each test checks one of these areas:

- Requests from one workspace that use another business's product, customer, order, supplier, purchase, website, enquiry, or invitation IDs are refused. The whole database must be unchanged afterwards.
- Users cannot select a business they don't belong to. Lists and reports in their own workspace contain no other business's records.
- In English, Hindi, and Telugu, the assistant answers only from the current business.
- Public websites show only their own business's catalog, and their enquiries reach only that business.
- Editors, sales staff, and platform admins get only the access their role allows, and invalid or logged-out sessions are rejected.
- Removing an agency member's access takes effect immediately.

Add a case for every new endpoint that accepts a record ID.

`tests/test_authentication.py` covers the following, using the in-memory fake email provider so no real email is sent:

- Sign-up with a code and single-use codes and tickets.
- Code expiry and replacement, and the five-attempt limit.
- Per-address and per-IP limits on code requests, per-IP limits on wrong codes, and per-account and per-IP limits on failed sign-ins.
- Existing accounts verifying on sign-in with their data and team intact, and old sessions blocked until they verify.
- Password reset, including signing out other sessions and responding the same way for unknown emails.
- Invitations limited to the invited email.
- Production refusing the test providers, SMTP over TLS, and codes kept out of logs and API responses.

`tests/test_agency_access.py` covers agency grants by access code and owner-only control. It also checks that inherited roles stay within each client's grant, unassigned staff see no clients, and assignments outside a grant give no access. The same cross-business requests are sent by agency users against a client that did not grant access. Revocation must take effect immediately while direct memberships survive. Further tests cover removing agency members and the onboarding owner handover.

`tests/test_agency_dashboard.py` covers combined and per-client totals, date filtering with refunds counted on their own dates, and staff seeing only assigned clients. It also covers editor website counts, unrelated direct memberships, other agencies' clients, and removal on the next request after unassignment or revocation.

## Public submission deployment

Use a dedicated demo backend and fictional data. The GoDaddy ZIP contains the React source and a Node.js server that forwards API requests to FastAPI.

1. Deploy the `backend` directory using its Dockerfile on a Python or container host. Attach persistent storage at `/data`, keep one backend instance for SQLite, and use the host's HTTPS origin. Set these secrets in the host's environment settings, never in the repository:
   - `VYAPARI_ENV=production`
   - `VYAPARI_SECRET_KEY`: 32 or more random characters.
   - `VYAPARI_PROXY_KEY`: 32 or more random characters, shared with the GoDaddy app.
   - `VYAPARI_EMAIL_PROVIDER=smtp` and the `VYAPARI_SMTP_*` and `VYAPARI_EMAIL_FROM` settings.

   Production refuses to start without the secret key and SMTP. Check that `/health` returns `ok`.
2. Seed the judge account on the backend host, next to its database, while the API runs. Set `VYAPARI_DEMO_PASSWORD` to a unique password of at least 16 characters, then run `python -m demo_seed --api http://127.0.0.1:$PORT` in the backend container. It creates a verified judge account, so judges sign in without an email code. It also creates the **Vyapari Demo Agency** with two fictional clients, **Asha Textiles** and **Ravi Home Goods**. Their products, suppliers, purchase orders, customers with phone numbers, paid, pending, and refunded orders, three published storefronts, and enquiries are created through the API. It prints the judge email and storefront paths. It never prints the password, and it refuses to run twice. Share the password privately.
3. Run `python hosting/package_zip.py vyapari-godaddy-YYYY-MM-DD.zip` from the project root to make a fresh ZIP. The ZIP contains only the frontend source, lockfiles, and the Node wrapper. It excludes the backend, SQLite files, backups, environment files, and dependency directories.
4. Authenticate with `gddy auth login`, then upload the ZIP to the GoDaddy app. Set server-side `VYAPARI_API_URL` to the backend HTTPS origin, and set `VYAPARI_PROXY_KEY` to the same value as the backend, in both Preview and Publish. With the proxy key, rate limits apply to each visitor rather than to the GoDaddy server as a whole. Test the preview before publishing.
5. Run the walkthrough from a signed-out browser. This needs Playwright and Microsoft Edge on the machine running the check:

   ```powershell
   $env:VYAPARI_DEMO_PASSWORD = "..."
   python hosting/verify_deployment.py https://YOUR-SITE before --storefront STOREFRONT-SLUG --state state.json
   # Restart the backend, then:
   python hosting/verify_deployment.py https://YOUR-SITE after --state state.json
   ```

   It checks judge sign-in, the agency dashboard, opening and switching clients, creating a paid order with stock and sales changes, a public storefront enquiry, and persistence after the backend restarts.

See the [GoDaddy CLI deployment guide](https://developer.godaddy.com/en/docs/api-users/hosting/workflows/deploy-nodejs-app) and [variant secrets guide](https://developer.godaddy.com/en/docs/api-users/hosting/manage-secrets).

## Local storage

Set `VYAPARI_DATABASE_PATH` in PowerShell before starting FastAPI to run against a different SQLite file. If it is unset, the app uses `backend/vyapari.db`.

### Backup and restore rehearsal

Run these commands from `backend`, using a private folder that already exists for the copy.

```powershell
.\.venv\Scripts\python.exe -m database_backup backup "C:\path\to\private\vyapari-backup.sqlite3"
.\.venv\Scripts\python.exe -m database_backup verify "C:\path\to\private\vyapari-backup.sqlite3"
.\.venv\Scripts\python.exe -m database_backup restore "C:\path\to\private\vyapari-backup.sqlite3" "C:\path\to\private\vyapari-rehearsal.sqlite3"
```

Backups include committed SQLite changes and are verified for integrity and foreign keys. Backup and restore require a new destination file. Copies contain business data and account records, so keep them private. To start a local rehearsal against the restored copy:

```powershell
$env:VYAPARI_DATABASE_PATH = "C:\path\to\private\vyapari-rehearsal.sqlite3"
.\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8001
```

Point a separate local frontend session to this backend by setting `VITE_API_BASE_URL=http://127.0.0.1:8001` before starting Vite. Use a separate PowerShell session for the main app so it keeps its original database settings.

GoDaddy is the target for production hosting and domains. The backup and rehearsal commands run locally.

Before moving data to PostgreSQL, check a verified SQLite backup and compare it with the rehearsal copy:

```powershell
.\.venv\Scripts\python.exe -m migration_check check "C:\path\to\private\vyapari-backup.sqlite3"
.\.venv\Scripts\python.exe -m migration_check compare "C:\path\to\private\vyapari-backup.sqlite3" "C:\path\to\private\vyapari-rehearsal.sqlite3"
```

The check reports row counts, missing schema requirements, and cross-business references. Compare checks row contents as well as counts before the rehearsal copy is modified. Both commands open their inputs read-only and report table names and counts without printing business records.

Create and verify a private data bundle for the migration rehearsal:

```powershell
.\.venv\Scripts\python.exe -m migration_export export "C:\path\to\private\vyapari-backup.sqlite3" "C:\path\to\private\vyapari-migration.zip"
.\.venv\Scripts\python.exe -m migration_export verify "C:\path\to\private\vyapari-migration.zip"
```

The bundle contains JSON Lines for each exported table, file checksums, row counts, and the highest allocated IDs for SQLite auto-increment tables. Sessions and invitation records are excluded. Bundle format 2 adds the agency tables, so create a new bundle with this version. Older bundles are rejected. The archive includes business records and password hashes, so keep it in a private location. It is an input for a future PostgreSQL import.

Generate a staging script from the verified bundle and run it with `psql` against a disposable PostgreSQL database once one is available:

```powershell
.\.venv\Scripts\python.exe -m postgres_rehearsal "C:\path\to\private\vyapari-migration.zip" "C:\path\to\private\vyapari-rehearsal.sql"
psql -X --dbname vyapari_rehearsal --file "C:\path\to\private\vyapari-rehearsal.sql"
```

Use your rehearsal server's connection settings for `psql`. The script creates a new `vyapari_rehearsal` schema, preserves original row payloads and sequence metadata, and verifies loaded row counts before commit. An existing schema with that name causes the load to fail. The script contains the same private data as the bundle. Staging is the input to the later typed PostgreSQL schema and application migration.

Generate the typed load from the same SQLite backup and bundle, then run it in the same disposable PostgreSQL database after staging:

```powershell
.\.venv\Scripts\python.exe -m postgres_typed_rehearsal "C:\path\to\private\vyapari-backup.sqlite3" "C:\path\to\private\vyapari-migration.zip" "C:\path\to\private\vyapari-typed-rehearsal.sql"
psql -X --dbname vyapari_rehearsal --file "C:\path\to\private\vyapari-typed-rehearsal.sql"
```

The typed load creates a fresh `vyapari_typed_rehearsal` schema, applies primary and foreign keys, compares table counts and staging metadata with the verified bundle, and advances ID sequences past imported and previously allocated IDs. It also carries over literal column defaults, secondary indexes, and unique indexes, including the pending website request and order inquiry rules. For SQLite `NOCASE` indexes, PostgreSQL uses an expression that folds ASCII letters. SQLite `CHECK` constraints are recreated as named PostgreSQL constraints, such as `products_stock_check`. Only simple comparisons with a number and fixed value lists are translated. Any other `CHECK` stops script generation for review. Before commit, the script confirms that the typed schema has the expected number of `CHECK` constraints. A failed validation or a row that breaks a constraint rolls back the typed load. The FastAPI database connection is a separate migration step.

FastAPI creates and updates `backend/vyapari.db` on startup. SQLite stores products, customers, orders, storefront drafts, assistant conversations, businesses, password hashes with salts, and session token hashes on this computer. Each business starts with an empty customer and order list. Sessions expire after 12 hours. The browser keeps the sign-in token in session storage so it can restore the session after a refresh in the same tab. Unsaved storefront edits and unsent questions reset on reload.

In **Orders → New order**, choose a saved customer and one or more stocked products. Saving deducts stock immediately for both Pending and Paid orders. Search Orders by order number, customer, or product and use the **Status** filter to narrow the results. **Cancel order** returns the items from a pending order to stock and keeps the order in history. Products in pending orders can be deleted once those orders are resolved. Marking a pending order paid updates sales analytics and customer lifetime value. Payment status records payments received outside the app.

Use **Refund order** on a paid order to record a full refund issued outside Vyapari AI. Select **Return all items to stock** if every item was returned and is available for resale. Net sales reflect payments less refunds, and the chart applies each refund on the date it was recorded. Customer lifetime value excludes refunded amounts.

In **Analytics**, choose a **Date range** and a **Sales channel** to report on all orders, direct orders, or orders attributed to a particular website. The **Enquiry conversion** panel counts enquiries received during the selected dates and shows their current customer and order links. **Export CSV** saves daily payments, refunds, and net sales in INR with a totals row and identifies the selected channel in the filename. Date boundaries follow India Standard Time.

In **Website Builder**, use **Create website** and select the website you want to edit. Under **Website catalog**, choose all products or select the individual products to show from the business's shared inventory. Save the draft and select **Publish locally** to create a read-only snapshot of its design and chosen product names and prices. **Publish update** refreshes that website at the same address. **Take down** disables its link, and publishing again creates a new one. Existing drafts and published links are migrated into **Main website** at startup. Both the frontend and backend must be running for local links to work.

Owners and managers can ask the platform team to provision an extra draft in **Website Builder → Website requests**. An authorized **Platform admin** can approve or decline each request from the platform directory. Approval creates an unpublished draft under the requesting business. Use **Refresh requests** to see the decision and reload the business's website list.

In **Website Builder**, owners and managers can rename a website, duplicate its saved design and product selection as a separate draft, or archive it. Archiving takes down its published link and keeps the draft available under **Archived websites**. Restore returns the draft to the editor. Publishing after a restore creates a new local link.

Enable **Show a contact form after publishing** on an individual website, save its draft, then publish or publish an update. Visitors can leave an enquiry with an email address or phone number. Owners and managers can filter **Website enquiries** by site or status and mark messages **New**, **In progress**, or **Resolved**. Messages are saved locally in SQLite for follow-up.

Open an enquiry's details to link an existing customer, create a customer from the contact information, or save internal notes. Once a customer is linked, **Create order from enquiry** preselects that customer and records the source website on the order. The enquiry then links back to the saved order.

In **AI Assistant**, try **Sales summary**, **Sales today**, **Sales last week**, **Inventory summary**, **Low stock**, **Recent orders**, or **Customer count**. You can look up a saved record using `Stock for Silk Saree` or `Order #ORD-123`. Sales reports support today, yesterday, this week, last week, last 7 days (including today), this month, and last month. Date ranges use India Standard Time and weeks start Monday. Payments and refunds count on their respective recorded dates.

The assistant accepts predefined Hindi and Telugu phrases and responds in the same language.

| Report | Hindi | Telugu |
| --- | --- | --- |
| Sales today | आज की बिक्री | ఈరోజు అమ్మకాలు |
| Inventory summary | कुल स्टॉक | మొత్తం స్టాక్ |
| Low stock | कम स्टॉक वाले उत्पाद | తక్కువ స్టాక్ ఉన్న ఉత్పత్తులు |
| Product stock | Silk Saree का स्टॉक | Silk Saree స్టాక్ ఎంత |
| Recent orders | हाल के ऑर्डर | ఇటీవలి ఆర్డర్లు |
| Order status | ऑर्डर #ORD-123 की स्थिति | ఆర్డర్ #ORD-123 స్థితి |
| Customer count | ग्राहकों की संख्या | కస్టమర్ల సంఖ్య |

Select **Read aloud** on a reply to play it through a local device voice. Playback follows the reply language and requires a matching voice exposed by your browser. Use **Stop reading** to end playback.

To dictate a question, choose a **Dictation language** and click the microphone. A supporting browser may first offer **Install language** to download its on-device speech pack. Allow microphone access if prompted. The transcript is added to the editable question box and is sent only when you click **Send**. Dictation is available only for languages and browsers that support on-device recognition.

Sent questions and their replies are saved for the signed-in business. Scroll to the top of the conversation to load older messages. Use **Clear history** to remove the saved conversation for that business.

## Next steps for Claude Code
1. Inspect `CLAUDE.md` and repository, run both applications, fix only confirmed startup issues.
2. Add Supabase authentication, business membership model, SQL migrations and RLS.
3. Replace session-only demo data with authenticated FastAPI CRUD and PostgreSQL persistence.
4. Add tests for tenant isolation and core business calculations.
5. Add approved AI tools, structured website builder persistence, voice, WhatsApp and phone integrations in phases.

## Safety and limitations
The SQLite catalog, sign-in, and storefront links are for local development. Live AI, WhatsApp, telephony, ads, payments, and public hosting are outside this demo. The demo customer details are fictional. Do not enter real customer data or deploy publicly as-is.
