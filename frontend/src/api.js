const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? (import.meta.env.DEV ? "http://127.0.0.1:8000" : "");

const SESSION_KEY = "vyapari.session";
const WORKSPACE_KEY = "vyapari.workspace";

export function getSessionToken() {
  return sessionStorage.getItem(SESSION_KEY);
}

export function setSessionToken(token) {
  if (getSessionToken() !== token || token === null) setActiveWorkspace(null);
  if (token) sessionStorage.setItem(SESSION_KEY, token);
  else sessionStorage.removeItem(SESSION_KEY);
}

export function setActiveWorkspace(businessId) {
  if (businessId == null) sessionStorage.removeItem(WORKSPACE_KEY);
  else sessionStorage.setItem(WORKSPACE_KEY, String(businessId));
}

export async function apiRequest(
  endpoint, options = {}, { authenticated = true, businessId = sessionStorage.getItem(WORKSPACE_KEY) } = {}
) {
  const token = authenticated ? getSessionToken() : null;
  const response = await fetch(`${API_BASE_URL}${endpoint}`, {
    ...options,
    headers: {
      ...(options.body && { "Content-Type": "application/json" }),
      ...(token && { Authorization: `Bearer ${token}` }),
      ...(token && businessId != null && { "X-Business-Id": String(businessId) }),
      ...options.headers,
    },
  });

  if (!response.ok) {
    if (response.status === 401 && token && token === getSessionToken()) {
      setSessionToken(null);
      window.dispatchEvent(new Event("vyapari-session-expired"));
    }
    const body = await response.json().catch(() => null);
    const detail = body?.detail;
    const message = Array.isArray(detail)
      ? detail.map(({ loc, msg }) => `${loc.at(-1)}: ${msg}`).join("; ")
      : typeof detail === "object" && detail ? detail.message : detail;
    const error = new Error(message || `API request failed: ${response.status}`);
    error.status = response.status;
    // Structured details, such as { code: "verification_required" } from sign-in.
    error.detail = detail;
    throw error;
  }

  return response.status === 204 ? null : response.json();
}

function postAuth(path, values) {
  return apiRequest(`/api/auth/${path}`, { method: "POST", body: JSON.stringify(values) }, { authenticated: false });
}

export const signIn = (email, password) => postAuth("login", { email, password });
export const verifySignIn = (email, password, code) => postAuth("login/verify", { email, password, code });
export const startSignup = (email) => postAuth("signup/start", { email });
export const verifySignup = (email, code) => postAuth("signup/verify", { email, code });
export const completeSignup = (ticket, password, businessName) =>
  postAuth("signup/complete", { ticket, password, business_name: businessName });
export const startPasswordReset = (email) => postAuth("password-reset/start", { email });
export const completePasswordReset = (email, code, password) =>
  postAuth("password-reset/complete", { email, code, password });
export const sendInvitationCode = (token) => postAuth("invitations/send-code", { token });

export function getAccount(signal, businessId) {
  return apiRequest("/api/auth/me", { signal, cache: "no-store" }, { businessId });
}

export function listWorkspaces(signal) {
  return apiRequest("/api/workspaces", { signal, cache: "no-store" });
}

export function createWorkspace(name) {
  return apiRequest("/api/workspaces", { method: "POST", body: JSON.stringify({ name }) });
}

export function listWorkspaceMembers(signal) {
  return apiRequest("/api/workspaces/members", { signal, cache: "no-store" });
}

export function grantWorkspaceMember(email, role) {
  return apiRequest("/api/workspaces/members", { method: "POST", body: JSON.stringify({ email, role }) });
}

export function updateWorkspaceMember(id, role) {
  return apiRequest(`/api/workspaces/members/${id}`, { method: "PUT", body: JSON.stringify({ role }) });
}

export function updateMemberWebsiteAccess(id, websiteIds) {
  return apiRequest(`/api/workspaces/members/${id}/websites`, {
    method: "PUT",
    body: JSON.stringify({ website_ids: websiteIds }),
  });
}

export function revokeWorkspaceMember(id) {
  return apiRequest(`/api/workspaces/members/${id}`, { method: "DELETE" });
}

export function listTeamInvitations(signal) {
  return apiRequest("/api/workspaces/invitations", { signal, cache: "no-store" });
}

export function createTeamInvitation(email, role) {
  return apiRequest("/api/workspaces/invitations", {
    method: "POST",
    body: JSON.stringify({ email, role }),
  });
}

export function revokeTeamInvitation(id) {
  return apiRequest(`/api/workspaces/invitations/${id}`, { method: "DELETE" });
}

export function previewInvitation(token, signal) {
  return apiRequest("/api/auth/invitations/preview", {
    method: "POST", body: JSON.stringify({ token }), signal, cache: "no-store",
  }, { authenticated: false });
}

export function acceptInvitation(token, password, code) {
  return apiRequest("/api/auth/invitations/accept", {
    method: "POST", body: JSON.stringify({ token, password, ...(code && { code }) }),
  }, { authenticated: false });
}

export function listPlatformBusinesses(signal) {
  return apiRequest("/api/platform/businesses", { signal, cache: "no-store" });
}

export function listWorkspaceActivity(signal, before) {
  const query = before == null ? "" : `?before=${encodeURIComponent(before)}`;
  return apiRequest(`/api/workspaces/activity${query}`, { signal, cache: "no-store" });
}

export function signOut() {
  return apiRequest("/api/auth/logout", { method: "POST" });
}

export async function checkBackendHealth() {
  return apiRequest("/health");
}

export function listProducts(signal) {
  return apiRequest("/api/products", { signal, cache: "no-store" });
}

export function createProduct(product) {
  return apiRequest("/api/products", {
    method: "POST",
    body: JSON.stringify(product),
  });
}

export function updateProduct(id, product) {
  return apiRequest(`/api/products/${id}`, {
    method: "PUT",
    body: JSON.stringify(product),
  });
}

export function deleteProduct(id) {
  return apiRequest(`/api/products/${id}`, { method: "DELETE" });
}

export function getStockHistory(id, signal, before = null) {
  const query = before == null ? "" : `?before=${encodeURIComponent(before)}`;
  return apiRequest(`/api/inventory/${id}/movements${query}`, { signal, cache: "no-store" });
}

export function adjustProductStock(id, adjustment) {
  return apiRequest(`/api/inventory/${id}/adjust`, {
    method: "POST",
    body: JSON.stringify(adjustment),
  });
}

export function listCustomers(signal) {
  return apiRequest("/api/customers", { signal, cache: "no-store" });
}

export function createCustomer(customer) {
  return apiRequest("/api/customers", {
    method: "POST",
    body: JSON.stringify(customer),
  });
}

export function updateCustomer(id, customer) {
  return apiRequest(`/api/customers/${id}`, {
    method: "PUT",
    body: JSON.stringify(customer),
  });
}

export function deleteCustomer(id) {
  return apiRequest(`/api/customers/${id}`, { method: "DELETE" });
}

export function listOrders(signal) {
  return apiRequest("/api/orders", { signal, cache: "no-store" });
}

export function createOrder(order) {
  return apiRequest("/api/orders", { method: "POST", body: JSON.stringify(order) });
}

export function markOrderPaid(id) {
  return apiRequest(`/api/orders/${id}/paid`, { method: "PUT" });
}

export function cancelOrder(id) {
  return apiRequest(`/api/orders/${id}/cancel`, { method: "PUT" });
}

export function refundOrder(id, restock) {
  return apiRequest(`/api/orders/${id}/refund`, {
    method: "PUT",
    body: JSON.stringify({ restock }),
  });
}

export function listWebsites(signal, includeArchived = false) {
  const query = includeArchived ? "?include_archived=true" : "";
  return apiRequest(`/api/storefront/sites${query}`, { signal, cache: "no-store" });
}

export function listWebsiteCatalog(signal) {
  return apiRequest("/api/storefront/catalog", { signal, cache: "no-store" });
}

export function createWebsite(label) {
  return apiRequest("/api/storefront/sites", { method: "POST", body: JSON.stringify({ label }) });
}

export function renameWebsite(id, label) {
  return apiRequest(`/api/storefront/sites/${id}`, { method: "PATCH", body: JSON.stringify({ label }) });
}

export function duplicateWebsite(id, label) {
  return apiRequest(`/api/storefront/sites/${id}/duplicate`, { method: "POST", body: JSON.stringify({ label }) });
}

export function setWebsiteArchived(id, archived) {
  return apiRequest(`/api/storefront/sites/${id}/archive`, { method: "PUT", body: JSON.stringify({ archived }) });
}

export function listWebsiteRequests(platformAdmin, signal) {
  const path = platformAdmin ? "/api/platform/website-requests" : "/api/storefront/requests";
  return apiRequest(path, { signal, cache: "no-store" });
}

export function createWebsiteRequest(label, notes) {
  return apiRequest("/api/storefront/requests", {
    method: "POST",
    body: JSON.stringify({ label, notes }),
  });
}

export function decideWebsiteRequest(id, status) {
  return apiRequest(`/api/platform/website-requests/${id}`, {
    method: "PUT",
    body: JSON.stringify({ status }),
  });
}

export function getStorefront(siteId, signal) {
  return apiRequest(`/api/storefront?site_id=${siteId}`, { signal, cache: "no-store" });
}

export function saveStorefront(siteId, draft) {
  return apiRequest(`/api/storefront?site_id=${siteId}`, { method: "PUT", body: JSON.stringify(draft) });
}

export function getPublication(siteId, signal) {
  return apiRequest(`/api/storefront/publication?site_id=${siteId}`, { signal, cache: "no-store" });
}

export function publishStorefront(siteId) {
  return apiRequest(`/api/storefront/publication?site_id=${siteId}`, { method: "PUT" });
}

export function unpublishStorefront(siteId) {
  return apiRequest(`/api/storefront/publication?site_id=${siteId}`, { method: "DELETE" });
}

export function getPublicStorefront(slug, signal) {
  return apiRequest(
    `/api/storefront/public/${encodeURIComponent(slug)}`,
    { signal, cache: "no-store" },
    { authenticated: false }
  );
}

export function sendWebsiteInquiry(slug, inquiry) {
  return apiRequest(`/api/storefront/public/${encodeURIComponent(slug)}/inquiries`, {
    method: "POST",
    body: JSON.stringify(inquiry),
  }, { authenticated: false });
}

export function listWebsiteInquiries(signal) {
  return apiRequest("/api/storefront/inquiries", { signal, cache: "no-store" });
}

export function updateWebsiteInquiry(id, status) {
  return apiRequest(`/api/storefront/inquiries/${id}/status`, {
    method: "PUT",
    body: JSON.stringify({ status }),
  });
}

export function saveWebsiteInquiryNotes(id, notes) {
  return apiRequest(`/api/storefront/inquiries/${id}/notes`, {
    method: "PUT",
    body: JSON.stringify({ notes }),
  });
}

export function linkWebsiteInquiryCustomer(id, customerId) {
  return apiRequest(`/api/storefront/inquiries/${id}/customer`, {
    method: "PUT",
    body: JSON.stringify({ customer_id: customerId }),
  });
}

export function createWebsiteInquiryCustomer(id) {
  return apiRequest(`/api/storefront/inquiries/${id}/customer`, { method: "POST" });
}

export function askAssistant(question, requestId) {
  return apiRequest("/api/assistant/ask", {
    method: "POST",
    body: JSON.stringify({ question, request_id: requestId }),
  });
}

export function getAssistantHistory(signal, before) {
  const query = before == null ? "" : `?before=${encodeURIComponent(before)}`;
  return apiRequest(`/api/assistant/history${query}`, { signal, cache: "no-store" });
}

export function clearAssistantHistory() {
  return apiRequest("/api/assistant/history", { method: "DELETE" });
}

export function getSalesReport(period, signal, channel = "all") {
  const query = new URLSearchParams({ period });
  if (channel === "direct") query.set("direct", "true");
  else if (channel !== "all") query.set("website_id", channel);
  return apiRequest(`/api/reports/sales?${query}`, {
    signal,
    cache: "no-store",
  });
}

// Client side: owners control agency access to the current business.
export function listAgencyGrants(signal) {
  return apiRequest("/api/workspaces/agencies", { signal, cache: "no-store" });
}

export function previewAgency(accessCode) {
  return apiRequest("/api/workspaces/agencies/preview", {
    method: "POST", body: JSON.stringify({ access_code: accessCode }),
  });
}

export function grantAgencyAccess(accessCode, role, websiteIds) {
  return apiRequest("/api/workspaces/agencies", {
    method: "POST", body: JSON.stringify({ access_code: accessCode, role, website_ids: websiteIds }),
  });
}

export function updateAgencyAccess(agencyId, role, websiteIds) {
  return apiRequest(`/api/workspaces/agencies/${agencyId}`, {
    method: "PUT", body: JSON.stringify({ role, website_ids: websiteIds }),
  });
}

export function revokeAgencyAccess(agencyId) {
  return apiRequest(`/api/workspaces/agencies/${agencyId}`, { method: "DELETE" });
}

// Agency side: agency accounts are independent of the selected business.
export function listAgencies(signal) {
  return apiRequest("/api/agencies", { signal, cache: "no-store" });
}

export function createAgency(name) {
  return apiRequest("/api/agencies", { method: "POST", body: JSON.stringify({ name }) });
}

export function listAgencyMembers(agencyId, signal) {
  return apiRequest(`/api/agencies/${agencyId}/members`, { signal, cache: "no-store" });
}

export function addAgencyMember(agencyId, email, role) {
  return apiRequest(`/api/agencies/${agencyId}/members`, { method: "POST", body: JSON.stringify({ email, role }) });
}

export function updateAgencyMember(agencyId, userId, role) {
  return apiRequest(`/api/agencies/${agencyId}/members/${userId}`, { method: "PUT", body: JSON.stringify({ role }) });
}

export function removeAgencyMember(agencyId, userId) {
  return apiRequest(`/api/agencies/${agencyId}/members/${userId}`, { method: "DELETE" });
}

export function listAgencyClients(agencyId, signal) {
  return apiRequest(`/api/agencies/${agencyId}/clients`, { signal, cache: "no-store" });
}

export function assignAgencyStaff(agencyId, businessId, userId, role) {
  return apiRequest(`/api/agencies/${agencyId}/clients/${businessId}/assignments/${userId}`, {
    method: "PUT", body: JSON.stringify({ role }),
  });
}

export function unassignAgencyStaff(agencyId, businessId, userId) {
  return apiRequest(`/api/agencies/${agencyId}/clients/${businessId}/assignments/${userId}`, { method: "DELETE" });
}

export function createAgencyClient(agencyId, businessName, ownerEmail) {
  return apiRequest(`/api/agencies/${agencyId}/clients`, {
    method: "POST", body: JSON.stringify({ business_name: businessName, owner_email: ownerEmail }),
  });
}

export function reissueOwnerInvitation(agencyId, businessId, email) {
  return apiRequest(`/api/agencies/${agencyId}/clients/${businessId}/owner-invitation`, {
    method: "POST", body: JSON.stringify({ email }),
  });
}

export function withdrawFromClient(agencyId, businessId) {
  return apiRequest(`/api/agencies/${agencyId}/clients/${businessId}`, { method: "DELETE" });
}

export function getAgencyDashboard(agencyId, period, signal) {
  return apiRequest(`/api/agencies/${agencyId}/dashboard?period=${encodeURIComponent(period)}`, { signal, cache: "no-store" });
}
