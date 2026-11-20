
import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
import {
  LayoutDashboard,
  Mail,
  Package,
  Users,
  ShoppingBag,
  BarChart3,
  Globe,
  MessageCircle,
  Settings,
  Search,
  Bell,
  ChevronDown,
  Plus,
  ArrowUpRight,
  Sparkles,
  Menu,
  X,
  CheckCircle2,
  ExternalLink,
  ShieldCheck,
  Briefcase,
} from "lucide-react";

import {
  ResponsiveContainer,
  AreaChart,
  Area,
  CartesianGrid,
  XAxis,
  YAxis,
  Tooltip,
} from "recharts";

import {
  askAssistant,
  cancelOrder,
  clearAssistantHistory,
  checkBackendHealth,
  createCustomer,
  createWebsite,
  listOrders,
  markOrderPaid,
  refundOrder,
  createProduct,
  deleteCustomer,
  deleteProduct,
  getAccount,
  getAssistantHistory,
  getPublication,
  getSalesReport,
  getSessionToken,
  getStorefront,
  listCustomers,
  listProducts,
  listWebsites,
  listWorkspaces,
  listWebsiteCatalog,
  publishStorefront,
  saveStorefront,
  setSessionToken,
  setActiveWorkspace,
  signOut,
  unpublishStorefront,
  updateCustomer,
  updateProduct,
} from "./api";
import SignIn from "./SignIn";
import OrderForm from "./OrderForm";
import OrderDetails from "./OrderDetails";
import InventoryDialog from "./InventoryDialog";
import Purchasing from "./Purchasing";
import RestockDialog from "./RestockDialog";
import useReplySpeech from "./useReplySpeech";
import AssistantComposer from "./AssistantComposer";
import { downloadSalesCsv } from "./salesCsv";
import { filterOrders, orderStatuses } from "./orderFilters";
import { restockList } from "./restock";
import WorkspaceSettings from "./WorkspaceSettings";
import WorkspaceActivity from "./WorkspaceActivity";
import InvitationAcceptance from "./InvitationAcceptance";
import TeamInvitations from "./TeamInvitations";
import PlatformBusinesses from "./PlatformBusinesses";
import Agencies from "./Agencies";
import AgencyAccess from "./AgencyAccess";
import { Stat, money, salesPeriods } from "./reporting";
import WebsiteRequests from "./WebsiteRequests";
import WebsiteLifecycle from "./WebsiteLifecycle";
import WebsiteInquiries from "./WebsiteInquiries";
import { workspaceRoleLabels } from "./workspaceRoles";

const nav = [
  ["Overview", LayoutDashboard],
  ["Products", Package],
  ["Purchasing", ShoppingBag],
  ["Customers", Users],
  ["Orders", ShoppingBag],
  ["Analytics", BarChart3],
  ["Website Builder", Globe],
  ["Website enquiries", Mail],
  ["AI Assistant", MessageCircle],
  ["Settings", Settings],
];

const salesDateFormat = new Intl.DateTimeFormat("en-IN", {
  day: "numeric", month: "short", year: "numeric", timeZone: "UTC",
});
const salesDayFormat = new Intl.DateTimeFormat("en-IN", {
  day: "numeric", month: "short", timeZone: "UTC",
});

const assistantPrompts = ["Sales summary", "Sales today", "Sales last week", "Inventory summary", "Low stock", "Recent orders", "Customer count"];
const localizedAssistantPrompts = [
  { text: "आज की बिक्री", language: "hi" },
  { text: "ఈరోజు అమ్మకాలు", language: "te" },
  { text: "कम स्टॉक वाले उत्पाद", language: "hi" },
  { text: "తక్కువ స్టాక్ ఉన్న ఉత్పత్తులు", language: "te" },
];

function chatLanguage(text) {
  const firstLetter = text.match(/\p{L}/u)?.[0] ?? "";
  if (/\p{Script=Devanagari}/u.test(firstLetter)) return "hi";
  if (/\p{Script=Telugu}/u.test(firstLetter)) return "te";
  return "en";
}

const emptyDraft = { name: "", category: "", price: "", stock: "", low_stock_threshold: "10", restock_target: "" };

function SectionTitle({ title, desc, action }) {
  return (
    <div className="section-title">
      <div>
        <h2>{title}</h2>
        <p>{desc}</p>
      </div>

      {action}
    </div>
  );
}

function OrdersTable({ orders, onOpen, onMarkPaid, onCancel, onRefund, busy }) {
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th>Order ID</th>
            <th>Customer</th>
            <th>Date</th>
            <th>Amount</th>
            <th>Status</th>
            {onMarkPaid && <th>Actions</th>}
          </tr>
        </thead>

        <tbody>
          {orders.map((order) => (
            <tr key={order.id}>
              <td>
                <button className="text-button order-number" type="button" onClick={() => onOpen(order.id)}>
                  #ORD-{order.id}
                </button>
                {onMarkPaid && (
                  <div className="muted">
                    {order.items.map((item) => `${item.quantity} × ${item.product}`).join(", ")}
                  </div>
                )}
              </td>

              <td>{order.customer}</td>
              <td>{new Date(order.date).toLocaleDateString("en-IN")}</td>
              <td>{money(order.amount_paise / 100)}</td>

              <td>
                <span
                  className={
                    "status " +
                    order.status.toLowerCase()
                  }
                >
                  {order.status}
                </span>
              </td>
              {onMarkPaid && (
                <td>
                  {order.status === "Pending" && (
                    <>
                      <button className="secondary" disabled={busy} onClick={() => onMarkPaid(order)}>
                        Mark paid
                      </button>{" "}
                      <button className="secondary" disabled={busy} onClick={() => onCancel(order)}>
                        Cancel order
                      </button>
                    </>
                  )}
                  {order.status === "Paid" && onRefund && (
                    <button className="secondary" disabled={busy} onClick={() => onRefund(order)}>
                      Refund order
                    </button>
                  )}
                  {order.status === "Refunded" && (
                    <span className="muted">
                      {new Date(order.refunded_at).toLocaleDateString("en-IN")} ·{" "}
                      {order.refund_restocked ? "Items returned to stock" : "Stock unchanged"}
                    </span>
                  )}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function App() {
  const [invite, setInvite] = useState(() => new URLSearchParams(window.location.hash.slice(1)).get("invite"));
  const [account, setAccount] = useState(null);
  const [checking, setChecking] = useState(() => Boolean(getSessionToken()));
  const [checkError, setCheckError] = useState("");
  const [checkAttempt, setCheckAttempt] = useState(0);
  const [sessionExpired, setSessionExpired] = useState(false);

  useEffect(() => {
    function expire() {
      setAccount(null);
      setChecking(false);
      setCheckError("");
      setSessionExpired(true);
    }
    window.addEventListener("vyapari-session-expired", expire);
    return () => window.removeEventListener("vyapari-session-expired", expire);
  }, []);

  useEffect(() => {
    const token = getSessionToken();
    if (!token) return;
    const controller = new AbortController();
    getAccount(controller.signal)
      .catch((error) => {
        if (error.status !== 403 && error.status !== 422) throw error;
        return getAccount(controller.signal, null).then((home) => {
          if (!controller.signal.aborted) setActiveWorkspace(null);
          return home;
        });
      })
      .then((current) => {
        if (!controller.signal.aborted && getSessionToken() === token) setAccount(current);
      })
      .catch((error) => {
        if (!controller.signal.aborted && getSessionToken() === token) {
          setCheckError(error.status === 403 ? error.message : "Could not connect to FastAPI to check your session.");
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setChecking(false);
      });
    return () => controller.abort();
  }, [checkAttempt]);

  function closeInvitation() {
    window.history.replaceState(null, "", window.location.pathname + window.location.search);
    setInvite(null);
  }

  if (invite) {
    return <InvitationAcceptance invite={invite} onCancel={closeInvitation} onAccept={({ token, ...current }) => {
      setSessionToken(token);
      setActiveWorkspace(current.business_id);
      setAccount(current);
      setChecking(false);
      setCheckError("");
      setSessionExpired(false);
      closeInvitation();
    }} />;
  }

  if (checking || checkError) {
    return (
      <main className="modal-backdrop">
        <div className="modal">
          {checking ? (
            <p role="status">Checking your session…</p>
          ) : (
            <>
              <p role="alert">{checkError}</p>
              <button className="primary" onClick={() => {
                setCheckError("");
                setChecking(true);
                setCheckAttempt((attempt) => attempt + 1);
              }}>
                Retry
              </button>
              <button className="text-button invitation-back" onClick={async () => {
                try {
                  await signOut();
                  setSessionToken(null);
                  setCheckError("");
                } catch {
                  setCheckError("Could not sign out. Check the backend connection and try again.");
                }
              }}>Sign out</button>
            </>
          )}
        </div>
      </main>
    );
  }
  if (!account) {
    return <SignIn sessionExpired={sessionExpired} onSignIn={(current) => {
      setSessionExpired(false);
      setAccount(current);
    }} />;
  }
  return <Dashboard key={account.business_id} account={account} onSelectWorkspace={async (id) => {
    const token = getSessionToken();
    const next = await getAccount(undefined, id);
    if (token !== getSessionToken()) return;
    setActiveWorkspace(next.business_id);
    setAccount(next);
  }} onSignOut={() => {
    setSessionToken(null);
    setAccount(null);
  }} />;
}

function Dashboard({ account, onSelectWorkspace, onSignOut }) {
  const isSalesStaff = account.role === "sales";
  const isWebsiteEditor = account.role === "website_editor";
  const canManageBusiness = !isSalesStaff && !isWebsiteEditor;
  const roleName = workspaceRoleLabels[account.role] +
    (account.access === "agency" && account.agency_names?.length ? ` · via ${account.agency_names.join(", ")}` : "");
  const [page, setPage] = useState(isWebsiteEditor ? "Website Builder" : isSalesStaff ? "Orders" : "Overview");
  const rolePages = isWebsiteEditor ? ["Website Builder", "Settings"]
    : isSalesStaff ? ["Products", "Customers", "Orders", "Settings"]
    : null;
  const workspaceNav = rolePages ? nav.filter(([name]) => rolePages.includes(name)) : nav;
  const [menu, setMenu] = useState(false);
  const [workspaces, setWorkspaces] = useState(null);
  const [workspaceAttempt, setWorkspaceAttempt] = useState(0);
  const [directoryVersion, setDirectoryVersion] = useState(0);
  const [workspaceError, setWorkspaceError] = useState("");
  const [switchingWorkspace, setSwitchingWorkspace] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    listWorkspaces(controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) setWorkspaces(data);
      })
      .catch((error) => {
        if (!controller.signal.aborted) setWorkspaceError(error.message);
      });
    return () => controller.abort();
  }, [workspaceAttempt]);

  async function switchWorkspace(id) {
    if (switchingWorkspace || id === account.business_id) return;
    setSwitchingWorkspace(true);
    setWorkspaceError("");
    try {
      await onSelectWorkspace(id);
    } catch (error) {
      setWorkspaceError(error.message);
    } finally {
      setSwitchingWorkspace(false);
    }
  }

  const [products, setProducts] = useState([]);
  const [productLoad, setProductLoad] = useState("loading");
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [productError, setProductError] = useState("");
  const [formError, setFormError] = useState("");
  const [productBusy, setProductBusy] = useState(false);
  const [customers, setCustomers] = useState(null);
  const [orders, setOrders] = useState([]);
  const [orderLoad, setOrderLoad] = useState("loading");
  const [orderSearch, setOrderSearch] = useState("");
  const [orderStatus, setOrderStatus] = useState("");
  const [orderAttempt, setOrderAttempt] = useState(0);
  const [orderError, setOrderError] = useState("");
  const [orderBusy, setOrderBusy] = useState(false);
  const visibleOrders = page === "Orders" ? filterOrders(orders, orderSearch, orderStatus) : [];
  const [showOrderForm, setShowOrderForm] = useState(false);
  const [orderInquiry, setOrderInquiry] = useState(null);
  const [detailOrderId, setDetailOrderId] = useState(null);
  const detailOrder = detailOrderId === null ? null : orders.find((order) => order.id === detailOrderId);
  const [refundDraft, setRefundDraft] = useState(null);
  const [refundError, setRefundError] = useState("");

  const [search, setSearch] = useState("");
  const [showProductForm, setShowProductForm] = useState(false);
  const [editingProductId, setEditingProductId] = useState(null);
  const [expectedProductStock, setExpectedProductStock] = useState(null);
  const [inventoryProductId, setInventoryProductId] = useState(null);
  const [showRestock, setShowRestock] = useState(false);
  const productsToRestock = page === "Products" && canManageBusiness ? restockList(products) : [];
  const inventoryProduct = products.find((product) => product.id === inventoryProductId);

  const [draft, setDraft] = useState(emptyDraft);

  const [assistantHistory, setAssistantHistory] = useState(null);
  const [historyError, setHistoryError] = useState("");
  const [historyAttempt, setHistoryAttempt] = useState(0);
  const [historyAction, setHistoryAction] = useState("");

  const [message, setMessage] = useState("");
  const [assistantBusy, setAssistantBusy] = useState(false);
  const [assistantError, setAssistantError] = useState("");
  const chatLog = useRef(null);
  const historyScroll = useRef(null);
  const pendingQuestion = useRef(null);
  const { listen, playback, stopReading } = useReplySpeech(page === "AI Assistant");
  const [dictating, setDictating] = useState(false);

  const [storefront, setStorefront] = useState(null);
  const [websites, setWebsites] = useState(null);
  const [selectedWebsite, setSelectedWebsite] = useState(null);
  const [websiteLabel, setWebsiteLabel] = useState("");
  const [websiteError, setWebsiteError] = useState("");
  const [websiteAttempt, setWebsiteAttempt] = useState(0);
  const [creatingWebsite, setCreatingWebsite] = useState(false);
  const [websiteLifecycleBusy, setWebsiteLifecycleBusy] = useState(false);
  const activeWebsites = websites?.filter((site) => !site.archived_at) ?? [];
  const archivedWebsites = websites?.filter((site) => site.archived_at) ?? [];
  const activeWebsite = activeWebsites.find((site) => site.id === selectedWebsite);
  const [storefrontLoadError, setStorefrontLoadError] = useState("");
  const [storefrontAttempt, setStorefrontAttempt] = useState(0);
  const [storefrontSaveState, setStorefrontSaveState] = useState("idle");
  const [storefrontSaveError, setStorefrontSaveError] = useState("");
  const [publication, setPublication] = useState(null);
  const [publicationAction, setPublicationAction] = useState("");
  const [publicationFeedback, setPublicationFeedback] = useState(null);
  const [signingOut, setSigningOut] = useState(false);
  const [signOutError, setSignOutError] = useState("");
  const {
    name: siteName = account.business_name,
    headline: siteHeadline = "Tradition, styled for today.",
    accent_color: siteColor = "#7158db",
    product_ids: websiteProductIds = null,
    accept_inquiries: websiteAcceptsInquiries = false,
  } = storefront ?? {};
  const selectedProductIds = new Set(websiteProductIds ?? []);
  const websiteProducts = websiteProductIds === null
    ? products
    : products.filter((product) => selectedProductIds.has(product.id));
  const storefrontSaving = storefrontSaveState === "saving";
  const websiteBusy = creatingWebsite || storefrontSaving || Boolean(publicationAction) || websiteLifecycleBusy;

  // Backend connection state
  const [backendStatus, setBackendStatus] = useState("Checking...");

  const [analyticsPeriod, setAnalyticsPeriod] = useState("last 7 days");
  const [analyticsChannel, setAnalyticsChannel] = useState("all");
  const [salesReport, setSalesReport] = useState(null);
  const [salesError, setSalesError] = useState("");
  const [salesAttempt, setSalesAttempt] = useState(0);
  const reportVisible = canManageBusiness && (page === "Overview" || page === "Analytics");
  const reportPeriod = page === "Analytics" ? analyticsPeriod : "last 7 days";
  const reportChannel = page === "Analytics" ? analyticsChannel : "all";
  const report = salesReport?.period === reportPeriod && salesReport?.channel === reportChannel
    ? salesReport.data : null;
  const totalSales = orders.reduce((sum, order) => (
    order.paid_at && !order.refunded_at ? sum + order.amount_paise : sum
  ), 0) / 100;
  const chart = report?.daily.map((day) => ({
    day: salesDayFormat.format(new Date(day.date)),
    sales: day.net_paise / 100,
  })) ?? [];
  const reportDates = report && (
    report.start_date === report.end_date
      ? salesDateFormat.format(new Date(report.start_date))
      : `${salesDateFormat.format(new Date(report.start_date))} – ${salesDateFormat.format(new Date(report.end_date))}`
  );
  const inventoryUnits = products.reduce(
    (sum, product) => sum + (product.stock ?? 0),
    0
  );

  const filtered = products.filter((product) =>
    (product.name + " " + product.category)
      .toLowerCase()
      .includes(search.toLowerCase())
  );

  async function checkApi() {
    setBackendStatus("Checking...");

    try {
      await checkBackendHealth();
      setBackendStatus("Connected");
    } catch (error) {
      console.error("Backend connection failed:", error);
      setBackendStatus("Disconnected");
    }
  }

  async function endSession() {
    setSigningOut(true);
    setSignOutError("");
    try {
      await signOut();
      onSignOut();
    } catch {
      setSignOutError("Could not sign out. Try again.");
      setSigningOut(false);
    }
  }

  // Check backend when the dashboard loads
  useEffect(() => {
    let active = true;

    async function verifyBackend() {
      try {
        await checkBackendHealth();

        if (active) {
          setBackendStatus("Connected");
        }
      } catch (error) {
        console.error("Backend connection failed:", error);

        if (active) {
          setBackendStatus("Disconnected");
        }
      }
    }

    verifyBackend();

    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const loadProducts = isWebsiteEditor ? listWebsiteCatalog : listProducts;
    loadProducts(controller.signal)
      .then((items) => {
        if (controller.signal.aborted) return;
        setProducts(items);
        setProductLoad("ready");
      })
      .catch(() => {
        if (!controller.signal.aborted) setProductLoad("error");
      });
    return () => controller.abort();
  }, [isWebsiteEditor, loadAttempt]);

  useEffect(() => {
    if (isWebsiteEditor) return;
    const controller = new AbortController();
    listOrders(controller.signal)
      .then((items) => {
        if (controller.signal.aborted) return;
        setOrders(items);
        setOrderLoad("ready");
      })
      .catch(() => {
        if (!controller.signal.aborted) setOrderLoad("error");
      });
    return () => controller.abort();
  }, [isWebsiteEditor, orderAttempt]);

  useEffect(() => {
    if (isSalesStaff) return;
    const controller = new AbortController();
    listWebsites(controller.signal, !isWebsiteEditor)
      .then((data) => {
        if (controller.signal.aborted) return;
        setWebsites(data);
        setSelectedWebsite((previous) => previous ?? data.find((site) => !site.archived_at)?.id ?? null);
      })
      .catch(() => {
        if (!controller.signal.aborted) setWebsiteError("Could not load this business’s websites.");
      });
    return () => controller.abort();
  }, [isSalesStaff, isWebsiteEditor, websiteAttempt]);

  useEffect(() => {
    if (selectedWebsite === null) return;
    const controller = new AbortController();
    Promise.all([getStorefront(selectedWebsite, controller.signal), getPublication(selectedWebsite, controller.signal)])
      .then(([draft, published]) => {
        if (controller.signal.aborted) return;
        setStorefront(draft);
        setPublication(published);
      })
      .catch(() => {
        if (!controller.signal.aborted) setStorefrontLoadError("Could not load the storefront draft.");
      });
    return () => controller.abort();
  }, [selectedWebsite, storefrontAttempt]);

  function openWebsite(id) {
    setStorefront(null);
    setPublication(null);
    setStorefrontLoadError("");
    setStorefrontSaveState("idle");
    setStorefrontSaveError("");
    setPublicationFeedback(null);
    setSelectedWebsite(id);
  }

  function canLeaveWebsite() {
    return storefrontSaveState !== "edited" || window.confirm("Discard the unsaved edits to this website?");
  }

  function applyWebsiteChange(website, action) {
    setWebsites((previous) => action === "duplicate"
      ? [...previous, website]
      : previous.map((item) => item.id === website.id ? website : item));
    if (action === "duplicate" || (action === "restore" && !activeWebsite)) {
      openWebsite(website.id);
    } else if (action === "archive" && selectedWebsite === website.id) {
      openWebsite(activeWebsites.find((site) => site.id !== website.id)?.id ?? null);
    }
  }

  async function addWebsite(event) {
    event.preventDefault();
    if (!websites || websiteBusy || !websiteLabel.trim() || !canLeaveWebsite()) return;
    setCreatingWebsite(true);
    setWebsiteError("");
    try {
      const website = await createWebsite(websiteLabel.trim());
      setWebsites((previous) => [...previous, website]);
      setWebsiteLabel("");
      openWebsite(website.id);
    } catch (error) {
      setWebsiteError(error.message);
    } finally {
      setCreatingWebsite(false);
    }
  }

  function editStorefront(field, value) {
    setStorefront((draft) => ({ ...draft, [field]: value }));
    setStorefrontSaveState("edited");
    setStorefrontSaveError("");
  }

  async function saveDraft() {
    if (!storefront || websiteBusy) return;
    setStorefrontSaveState("saving");
    setStorefrontSaveError("");
    try {
      setStorefront(await saveStorefront(selectedWebsite, storefront));
      setStorefrontSaveState("saved");
    } catch (error) {
      setStorefrontSaveError(`Could not save draft. ${error.message}`);
      setStorefrontSaveState("edited");
    }
  }

  async function changePublication(unpublish = false) {
    if (websiteBusy) return;
    const prompt = unpublish
      ? "Take down the storefront? Its current link will stop working."
      : "Publish the saved storefront and its chosen product names and prices to a local link?";
    if (!window.confirm(prompt)) return;

    setPublicationAction(unpublish ? "unpublishing" : "publishing");
    setPublicationFeedback(null);
    try {
      if (unpublish) {
        await unpublishStorefront(selectedWebsite);
        setPublication(null);
        setPublicationFeedback({ message: "Storefront taken down." });
      } else {
        setPublication(await publishStorefront(selectedWebsite));
        setPublicationFeedback({ message: "Storefront published locally." });
      }
      setWebsites((previous) => previous.map((site) => (
        site.id === selectedWebsite ? { ...site, published: !unpublish } : site
      )));
    } catch (error) {
      setPublicationFeedback({ error: true, message: error.message });
    } finally {
      setPublicationAction("");
    }
  }

  useEffect(() => {
    if (!reportVisible) return;
    const controller = new AbortController();
    setSalesReport(null);
    setSalesError("");
    getSalesReport(reportPeriod, controller.signal, reportChannel)
      .then((data) => {
        if (!controller.signal.aborted) setSalesReport({ period: reportPeriod, channel: reportChannel, data });
      })
      .catch(() => {
        if (!controller.signal.aborted) setSalesError("Could not load this sales report.");
      });
    return () => controller.abort();
  }, [reportVisible, reportPeriod, reportChannel, salesAttempt, orders]);

  function onOrderSaved(order) {
    setOrders((previous) => [order, ...previous.filter((item) => item.id !== order.id)]);
    setShowOrderForm(false);
    setOrderInquiry(null);
    setProductLoad("loading");
    setLoadAttempt((attempt) => attempt + 1);
  }

  async function recordPayment(order) {
    if (orderBusy || !window.confirm(`Mark order #ORD-${order.id} as paid?`)) return;
    setOrderBusy(true);
    setOrderError("");
    try {
      const updated = await markOrderPaid(order.id);
      setOrders((previous) => previous.map((item) => item.id === updated.id ? updated : item));
    } catch (error) {
      setOrderError(`Could not mark order paid. ${error.message}`);
    } finally {
      setOrderBusy(false);
    }
  }

  async function cancelPendingOrder(order) {
    if (orderBusy || !window.confirm(`Cancel order #ORD-${order.id} and return its items to stock?`)) return;
    setOrderBusy(true);
    setOrderError("");
    try {
      const updated = await cancelOrder(order.id);
      setOrders((previous) => previous.map((item) => item.id === updated.id ? updated : item));
      setProductLoad("loading");
      setLoadAttempt((attempt) => attempt + 1);
    } catch (error) {
      setOrderError(`Could not cancel order. ${error.message}`);
    } finally {
      setOrderBusy(false);
    }
  }

  async function recordRefund(event) {
    event.preventDefault();
    if (orderBusy) return;
    setOrderBusy(true);
    setRefundError("");
    try {
      const updated = await refundOrder(refundDraft.order.id, refundDraft.restock);
      setOrders((previous) => previous.map((item) => item.id === updated.id ? updated : item));
      setRefundDraft(null);
      if (updated.refund_restocked) {
        setProductLoad("loading");
        setLoadAttempt((attempt) => attempt + 1);
      }
    } catch (error) {
      setRefundError(`Could not record refund. ${error.message}`);
    } finally {
      setOrderBusy(false);
    }
  }

  function openProductForm(product) {
    setFormError("");
    setEditingProductId(product?.id ?? null);
    setExpectedProductStock(product?.stock ?? null);
    setDraft(
      product
        ? {
            name: product.name,
            category: product.category,
            price: String(product.price),
            stock: String(product.stock),
            low_stock_threshold: String(product.low_stock_threshold ?? 10),
            restock_target: product.restock_target == null ? "" : String(product.restock_target),
          }
        : emptyDraft
    );
    setShowProductForm(true);
  }

  async function saveProduct(event) {
    event.preventDefault();
    if (productBusy || productLoad !== "ready") return;

    setFormError("");
    setProductError("");
    setProductBusy(true);
    try {
      const values = {
        name: draft.name.trim(),
        category: draft.category.trim(),
        price: Number(draft.price),
        stock: Number(draft.stock),
        low_stock_threshold: Number(draft.low_stock_threshold),
        restock_target: draft.restock_target === "" ? null : Number(draft.restock_target),
      };
      if (editingProductId === null) {
        const product = await createProduct(values);
        setProducts((previous) => [product, ...previous]);
      } else {
        const product = await updateProduct(editingProductId, { ...values, expected_stock: expectedProductStock });
        setProducts((previous) =>
          previous.map((item) => (item.id === product.id ? product : item))
        );
      }
      setShowProductForm(false);
    } catch (error) {
      setFormError(`Could not save product. ${error.message}`);
      if (error.status === 409 && editingProductId !== null) {
        setProductLoad("loading");
        setLoadAttempt((attempt) => attempt + 1);
      }
    } finally {
      setProductBusy(false);
    }
  }

  async function removeProduct(product) {
    if (productBusy || !window.confirm(`Delete "${product.name}"?`)) return;

    setProductError("");
    setProductBusy(true);
    try {
      await deleteProduct(product.id);
      setProducts((previous) => previous.filter((item) => item.id !== product.id));
      setStorefront((draft) => draft?.product_ids?.includes(product.id)
        ? { ...draft, product_ids: draft.product_ids.filter((id) => id !== product.id) }
        : draft);
    } catch (error) {
      setProductError(`Could not delete product. ${error.message}`);
    } finally {
      setProductBusy(false);
    }
  }

  useEffect(() => {
    if (!canManageBusiness) return;
    const controller = new AbortController();
    getAssistantHistory(controller.signal)
      .then((history) => {
        if (!controller.signal.aborted) setAssistantHistory(history);
      })
      .catch(() => {
        if (!controller.signal.aborted) setHistoryError("Could not load assistant history.");
      });
    return () => controller.abort();
  }, [canManageBusiness, historyAttempt]);

  useLayoutEffect(() => {
    const log = chatLog.current;
    const previous = historyScroll.current;
    historyScroll.current = null;
    if (log) {
      log.scrollTop = previous
        ? previous.top + log.scrollHeight - previous.height
        : log.scrollHeight;
    }
  }, [assistantHistory, assistantBusy, page]);

  const assistantDisabled = !assistantHistory || assistantBusy || Boolean(historyAction);
  const messages = page === "AI Assistant" ? [
    ...(!assistantHistory?.older_before ? [{
      id: "greeting",
      who: "ai",
      text: "Namaste! Ask for a sales summary, low-stock products, recent orders, or your customer count.",
    }] : []),
    ...(assistantHistory?.exchanges ?? []).flatMap((exchange) => [
      { id: `question-${exchange.id}`, who: "user", text: exchange.question },
      { id: `reply-${exchange.id}`, who: "ai", text: exchange.answer, language: exchange.language },
    ]),
  ] : [];

  async function submitQuestion(text) {
    const question = text.trim();
    if (!question || assistantDisabled || dictating) return;

    setAssistantBusy(true);
    setAssistantError("");
    setMessage(question);
    try {
      if (pendingQuestion.current?.question !== question) {
        pendingQuestion.current = { question, requestId: crypto.randomUUID() };
      }
      const exchange = await askAssistant(question, pendingQuestion.current.requestId);
      setAssistantHistory((previous) => ({
        ...previous,
        exchanges: [...previous.exchanges.filter((item) => item.id !== exchange.id), exchange],
      }));
      pendingQuestion.current = null;
      setMessage("");
    } catch (error) {
      setAssistantError(`Could not get an answer. ${error.message}`);
    } finally {
      setAssistantBusy(false);
    }
  }

  async function loadOlderHistory() {
    if (assistantDisabled || dictating || !assistantHistory.older_before) return;
    setHistoryAction("loading older");
    setHistoryError("");
    try {
      const older = await getAssistantHistory(undefined, assistantHistory.older_before);
      const log = chatLog.current;
      if (log) historyScroll.current = { top: log.scrollTop, height: log.scrollHeight };
      setAssistantHistory((previous) => ({
        exchanges: [...older.exchanges, ...previous.exchanges],
        older_before: older.older_before,
      }));
    } catch {
      setHistoryError("Could not load older messages. Try again.");
    } finally {
      setHistoryAction("");
    }
  }

  async function deleteHistory() {
    if (assistantDisabled || dictating || !assistantHistory.exchanges.length) return;
    if (!window.confirm("Permanently clear the saved assistant conversation for this business?")) return;
    setHistoryAction("clearing");
    setHistoryError("");
    try {
      await clearAssistantHistory();
      stopReading();
      pendingQuestion.current = null;
      setAssistantHistory({ exchanges: [], older_before: null });
    } catch {
      setHistoryError("Could not clear the conversation. Try again.");
    } finally {
      setHistoryAction("");
    }
  }

  return (
    <div className="shell">
      {/* SIDEBAR */}
      <aside className={"sidebar " + (menu ? "open" : "")}>
        <div className="brand">
          <span className="brand-icon">
            <Sparkles size={21} />
          </span>

          <span>
            vyapari
            <span className="brand-ai">ai</span>
            <small>BUSINESS OS</small>
          </span>

          <button
            className="mobile-close"
            onClick={() => setMenu(false)}
            aria-label="Close menu"
          >
            <X />
          </button>
        </div>

        <div className="workspace-label">WORKSPACE</div>

        <div className="business-switch">
          <span className="avatar">{account.business_name[0].toUpperCase()}</span>

          <span className="workspace-select">
            <strong>{account.business_name}</strong>
            <small>{roleName}</small>
            {workspaces && workspaces.length > 1 && (
              <select
                aria-label="Switch business"
                value={account.business_id}
                disabled={switchingWorkspace}
                onChange={(event) => switchWorkspace(Number(event.target.value))}
              >
                {workspaces.map((workspace) => (
                  <option key={workspace.id} value={workspace.id}>{workspace.name} · #{workspace.id}{workspace.access === "agency" ? " · agency" : ""}</option>
                ))}
              </select>
            )}
          </span>
        </div>
        {switchingWorkspace && <p className="workspace-feedback" role="status">Switching business…</p>}
        {workspaceError && <p className="workspace-feedback" role="alert">{workspaceError}</p>}

        <div className="nav-label">MAIN MENU</div>

        <nav>
          {[...workspaceNav, ["Agencies", Briefcase], ...(account.is_platform_admin ? [["Platform admin", ShieldCheck]] : [])].map(([name, Icon]) => (
            <button
              key={name}
              className={
                "nav-item " + (page === name ? "active" : "")
              }
              onClick={() => {
                setPage(name);
                setSearch("");
                setMenu(false);
              }}
            >
              <Icon size={19} />

              {name}

              {name === "AI Assistant" && (
                <span className="new-tag">AI</span>
              )}
            </button>
          ))}
        </nav>

        <div className="sidebar-bottom">
          {canManageBusiness && <div className="upgrade">
            <span>✨ AI-powered growth</span>

            <p>Your business, managed in your language.</p>

            <button onClick={() => setPage("AI Assistant")}>
              Try AI Assistant
              <ArrowUpRight size={14} />
            </button>
          </div>}

          <div className="profile">
            <span className="avatar profile-avatar">D</span>

            <span>
              <strong>{roleName}</strong>
              <small>Local workspace</small>
            </span>

            <Settings size={17} />
          </div>
        </div>
      </aside>

      {/* MAIN CONTENT */}
      <main className="main">
        {/* TOP NAVIGATION */}
        <header className="topbar">
          <div className="top-left">
            <button
              className="hamburger"
              onClick={() => setMenu(true)}
              aria-label="Open menu"
            >
              <Menu />
            </button>

            <span className="breadcrumb">Workspace</span>
            <span className="slash">/</span>
            <strong>{page}</strong>
          </div>

          <div className="top-actions">
            {/* Backend status indicator */}
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: "5px",
                fontSize: "13px",
              }}
            >
              <span>Backend:</span>

              <strong
                style={{
                  color:
                    backendStatus === "Connected"
                      ? "#16a34a"
                      : backendStatus === "Disconnected"
                        ? "#dc2626"
                        : "#d97706",
                }}
              >
                {backendStatus}
              </strong>
            </div>

            <span className="demo-pill">
              <span className="dot" />
              Demo Mode
            </span>

            <button
              className="icon-button"
              aria-label="Notifications"
            >
              <Bell size={19} />
            </button>

            <span className="avatar top-avatar">D</span>
          </div>
        </header>

        <div className="content">
          {/* OVERVIEW */}
          {page === "Overview" && canManageBusiness && (
            <>
              <div className="welcome">
                <div>
                  <div className="eyebrow">
                    {new Date().toLocaleDateString("en-IN", { dateStyle: "long" })}
                  </div>

                  <h1>
                    Welcome, business owner <span>✳</span>
                  </h1>

                  <p>
                    Here's what's happening with your business.
                  </p>
                </div>

                <button
                  className="primary"
                  onClick={() => setPage("AI Assistant")}
                >
                  <Sparkles size={17} />
                  Ask AI Assistant
                </button>
              </div>

              <div className="stats">
                <Stat
                  label="Net sales"
                  value={orderLoad === "ready" ? money(totalSales) : "—"}
                  change="Payments less refunds"
                  icon={BarChart3}
                />

                <Stat
                  label="Total orders"
                  value={orderLoad === "ready" ? orders.length : "—"}
                  change="Including pending"
                  icon={ShoppingBag}
                />

                <Stat
                  label="Customers"
                  value={customers?.length ?? "—"}
                  change="Saved contacts"
                  icon={Users}
                />

                <Stat
                  label="Active products"
                  value={products.length}
                  change="In your catalog"
                  icon={Package}
                />
              </div>

              <div className="two-col">
                <div className="panel">
                  <div className="panel-head">
                    <div>
                      <h3>Sales overview</h3>
                      <p>Payments and refunds by date · IST</p>
                    </div>

                    <span className="select-chip">
                      Last 7 days
                      <ChevronDown size={14} />
                    </span>
                  </div>

                  {salesError ? (
                    <div className="empty">
                      <p role="alert">{salesError}</p>
                      <button className="secondary" onClick={() => setSalesAttempt((attempt) => attempt + 1)}>Retry</button>
                    </div>
                  ) : !report ? (
                    <p className="empty" role="status">Loading sales report…</p>
                  ) : (
                    <div className="chart">
                      <ResponsiveContainer
                        width="100%"
                        height="100%"
                      >
                        <AreaChart
                          data={chart}
                          margin={{
                            top: 10,
                            right: 8,
                            left: -22,
                            bottom: 0,
                          }}
                        >
                          <defs>
                            <linearGradient
                              id="area"
                              x1="0"
                              y1="0"
                              x2="0"
                              y2="1"
                            >
                              <stop
                                offset="0%"
                                stopColor="#7458df"
                                stopOpacity={0.2}
                              />

                              <stop
                                offset="100%"
                                stopColor="#7458df"
                                stopOpacity={0}
                              />
                            </linearGradient>
                          </defs>

                          <CartesianGrid
                            stroke="#eeeef4"
                            vertical={false}
                          />

                          <XAxis
                            dataKey="day"
                            axisLine={false}
                            tickLine={false}
                            tick={{
                              fill: "#9695a7",
                              fontSize: 12,
                            }}
                          />

                          <YAxis
                            axisLine={false}
                            tickLine={false}
                            tick={{
                              fill: "#9695a7",
                              fontSize: 12,
                            }}
                          />

                          <Tooltip formatter={(value) => money(value)} />

                          <Area
                            type="monotone"
                            dataKey="sales"
                            stroke="#7357d9"
                            strokeWidth={3}
                            fill="url(#area)"
                          />
                        </AreaChart>
                      </ResponsiveContainer>
                    </div>
                  )}
                </div>

                <div className="panel assistant-card">
                  <div className="ai-glyph">
                    <Sparkles size={25} />
                  </div>

                  <div className="mini-label">
                    YOUR BUSINESS COPILOT
                  </div>

                  <h3>Meet your AI business assistant</h3>

                  <p>
                    Ask about recorded sales, stock levels, and recent orders.
                  </p>

                  <button
                    type="button"
                    className="suggestion"
                    disabled={assistantDisabled || dictating}
                    onClick={() => {
                      setPage("AI Assistant");
                      submitQuestion("Sales summary");
                    }}
                  >
                    “How are my sales doing?”
                    <ArrowUpRight size={16} />
                  </button>

                  <button
                    className="dark-button"
                    onClick={() => setPage("AI Assistant")}
                  >
                    Open AI Assistant
                    <ArrowUpRight size={17} />
                  </button>
                </div>
              </div>

              <div className="panel recent">
                <div className="panel-head">
                  <div>
                    <h3>Recent orders</h3>
                    <p>Your latest recorded orders</p>
                  </div>

                  <button
                    className="text-button"
                    onClick={() => setPage("Orders")}
                  >
                    View all
                    <ArrowUpRight size={15} />
                  </button>
                </div>

                <OrdersTable orders={orders.slice(0, 5)} onOpen={setDetailOrderId} />
                {orders.length === 0 && <p className="empty">{orderLoad === "ready" ? "No orders yet." : "Orders unavailable."}</p>}
              </div>
            </>
          )}

          {/* PRODUCTS */}
          {page === "Products" && !isWebsiteEditor && (
            <>
              <SectionTitle
                title="Products & inventory"
                desc={isSalesStaff ? "Look up product prices and stock." : "Manage the products in your storefront."}
                action={!isSalesStaff && (
                  <div className="sales-actions">
                    <button className="secondary" type="button" disabled={productLoad !== "ready" || productBusy}
                      onClick={() => setShowRestock(true)}>Restock list ({productsToRestock.length})</button>
                    <button
                      className="primary"
                      disabled={productLoad !== "ready" || productBusy}
                      onClick={() => openProductForm()}
                    >
                      <Plus size={17} />
                      Add product
                    </button>
                  </div>
                )}
              />

              <div className="panel">
                <div className="toolbar">
                  <div className="search">
                    <Search size={17} />

                    <input
                      placeholder="Search products..."
                      value={search}
                      onChange={(event) =>
                        setSearch(event.target.value)
                      }
                    />
                  </div>

                  <span className="muted">
                    {filtered.length} products
                  </span>
                </div>

                <div className="table-scroll">
                  {productError && <p className="empty" role="alert">{productError}</p>}
                  <table>
                    <thead>
                      <tr>
                        <th>Product</th>
                        <th>Category</th>
                        <th>Price</th>
                        <th>Stock</th>
                        <th>Status</th>
                        {!isSalesStaff && <th>Actions</th>}
                      </tr>
                    </thead>

                    <tbody>
                      {filtered.map((product) => (
                        <tr key={product.id}>
                          <td>
                            <span className="product-icon">
                              📦
                            </span>

                            <strong>{product.name}</strong>
                          </td>

                          <td>
                            {product.category || "Uncategorized"}
                          </td>

                          <td>{money(product.price)}</td>
                          <td>{product.stock}</td>

                          <td>
                            <span
                              className={
                                "status " +
                                (product.stock < (product.low_stock_threshold ?? 10)
                                  ? "pending"
                                  : "paid")
                              }
                            >
                              {product.stock < (product.low_stock_threshold ?? 10)
                                ? "Low stock"
                                : "In stock"}
                            </span>
                          </td>
                          {!isSalesStaff && <td>
                            <button
                              type="button"
                              className="secondary"
                              disabled={productBusy || productLoad !== "ready"}
                              aria-label={`Manage stock for ${product.name}`}
                              onClick={() => setInventoryProductId(product.id)}
                            >
                              Stock
                            </button>{" "}
                            <button
                              type="button"
                              className="secondary"
                              disabled={productBusy}
                              aria-label={`Edit ${product.name}`}
                              onClick={() => openProductForm(product)}
                            >
                              Edit
                            </button>{" "}
                            <button
                              type="button"
                              className="secondary"
                              disabled={productBusy}
                              aria-label={`Delete ${product.name}`}
                              onClick={() => removeProduct(product)}
                            >
                              Delete
                            </button>
                          </td>}
                        </tr>
                      ))}
                    </tbody>
                  </table>

                  {productLoad === "loading" && (
                    <p className="empty" role="status">Loading products…</p>
                  )}
                  {productLoad === "error" && (
                    <div className="empty">
                      <p role="alert">Could not load products. Check that FastAPI is running.</p>
                      <button
                        className="secondary"
                        onClick={() => {
                          setProductLoad("loading");
                          setLoadAttempt((attempt) => attempt + 1);
                        }}
                      >
                        Retry
                      </button>
                    </div>
                  )}
                  {productLoad === "ready" && filtered.length === 0 && (
                    <p className="empty">
                      {products.length === 0 ? "No products yet." : "No matching products."}
                    </p>
                  )}
                </div>
              </div>
            </>
          )}

          {!isWebsiteEditor && <Customers
            active={page === "Customers"}
            customers={customers}
            setCustomers={setCustomers}
            orders={orderLoad === "ready" ? orders : null}
            canDelete={!isSalesStaff}
          />}

          {page === "Purchasing" && canManageBusiness && (
            <>
              <SectionTitle title="Purchasing" desc="Manage suppliers, record purchase orders, and receive stock." />
              <Purchasing products={products} productsReady={productLoad === "ready"} onReceived={() => {
                setProductLoad("loading");
                setLoadAttempt((attempt) => attempt + 1);
              }} />
            </>
          )}

          {/* ORDERS */}
          {page === "Orders" && !isWebsiteEditor && (
            <>
              <SectionTitle
                title="Orders"
                desc="Record sales and track payment status."
                action={
                  <button
                    className="primary"
                    disabled={orderLoad !== "ready" || productLoad !== "ready" || !customers?.length || !products.some((product) => product.stock > 0) || orderBusy}
                    onClick={() => setShowOrderForm(true)}
                  >
                    <Plus size={17} />
                    New order
                  </button>
                }
              />

              <div className="panel">
                {orderError && <p className="empty" role="alert">{orderError}</p>}
                {orderLoad === "error" ? (
                  <div className="empty">
                    <p role="alert">Could not load orders. Check that FastAPI is running.</p>
                    <button className="secondary" onClick={() => {
                      setOrderLoad("loading");
                      setOrderAttempt((attempt) => attempt + 1);
                    }}>Retry</button>
                  </div>
                ) : orderLoad === "loading" ? (
                  <p className="empty" role="status">Loading orders…</p>
                ) : (
                  <>
                    <div className="toolbar order-filters">
                      <div className="search">
                        <Search size={17} aria-hidden="true" />
                        <input
                          type="search"
                          aria-label="Search orders"
                          placeholder="Order number, customer, or product"
                          value={orderSearch}
                          onChange={(event) => setOrderSearch(event.target.value)}
                        />
                      </div>
                      <label className="sales-period">
                        Status
                        <select value={orderStatus} onChange={(event) => setOrderStatus(event.target.value)}>
                          <option value="">All statuses</option>
                          {orderStatuses.map((status) => <option key={status}>{status}</option>)}
                        </select>
                      </label>
                      <span className="muted" role="status">
                        {visibleOrders.length} of {orders.length} orders
                      </span>
                    </div>
                    <OrdersTable
                      orders={visibleOrders}
                      onOpen={setDetailOrderId}
                      onMarkPaid={recordPayment}
                      onCancel={cancelPendingOrder}
                      onRefund={isSalesStaff ? undefined : (order) => {
                        setOrderError("");
                        setRefundError("");
                        setRefundDraft({ order, restock: false });
                      }}
                      busy={orderBusy}
                    />
                    {orders.length === 0 && <p className="empty">No orders yet.</p>}
                    {orders.length > 0 && visibleOrders.length === 0 && (
                      <div className="empty">
                        <p>No orders match your filters.</p>
                        <button className="secondary" type="button" onClick={() => {
                          setOrderSearch("");
                          setOrderStatus("");
                        }}>Clear filters</button>
                      </div>
                    )}
                    {customers?.length === 0 && <p className="empty">Add a customer to record an order.</p>}
                    {productLoad === "ready" && !products.some((product) => product.stock > 0) && (
                      <p className="empty">Add stock to a product to record an order.</p>
                    )}
                  </>
                )}
              </div>
            </>
          )}

          {/* ANALYTICS */}
          {page === "Analytics" && canManageBusiness && (
            <>
              <SectionTitle
                title="Sales analytics"
                desc="Compare recorded payments and refunds by date."
                action={
                  <div className="sales-actions">
                    <label className="sales-period">
                      Date range
                      <select value={analyticsPeriod} onChange={(event) => {
                        setSalesError("");
                        setAnalyticsPeriod(event.target.value);
                      }}>
                        {salesPeriods.map((period) => (
                          <option key={period} value={period}>{period[0].toUpperCase() + period.slice(1)}</option>
                        ))}
                      </select>
                    </label>
                    <label className="sales-period">
                      Sales channel
                      <select value={analyticsChannel} onChange={(event) => {
                        setSalesError("");
                        setAnalyticsChannel(event.target.value);
                      }}>
                        <option value="all">All channels</option>
                        <option value="direct">Direct orders</option>
                        {websites?.map((site) => (
                          <option key={site.id} value={site.id}>
                            {site.label}{site.archived_at ? " (Archived)" : ""}
                          </option>
                        ))}
                      </select>
                    </label>
                    <button className="secondary" type="button" onClick={() => setSalesAttempt((attempt) => attempt + 1)}>
                      Refresh report
                    </button>
                    <button className="secondary" type="button" disabled={!report} onClick={() => downloadSalesCsv(report)}>
                      Export CSV
                    </button>
                  </div>
                }
              />

              <div className="stats">
                <Stat
                  label="Net sales"
                  value={report ? money(report.net_paise / 100) : "—"}
                  change="Payments less refunds"
                  icon={BarChart3}
                />

                <Stat
                  label="Paid orders"
                  value={report?.payment_count ?? "—"}
                  change={report ? `${money(report.payments_paise / 100)} received` : "Recorded payments"}
                  icon={ShoppingBag}
                />

                <Stat
                  label="Average paid order"
                  value={report?.payment_count ? money(report.payments_paise / 100 / report.payment_count) : "—"}
                  change="Recorded payments"
                  icon={ArrowUpRight}
                />

                <Stat
                  label="Refunds"
                  value={report ? money(report.refunds_paise / 100) : "—"}
                  change={report ? `${report.refund_count} recorded` : "Recorded refunds"}
                  icon={ArrowUpRight}
                />
              </div>

              <div className="panel">
                <div className="panel-head">
                  <div>
                    <h3>Daily net sales</h3>

                    <p>{reportDates ? `${report.channel.label} · ${reportDates} · IST` : "Payments and refunds by date"}</p>
                  </div>
                </div>

                {salesError ? (
                  <div className="empty">
                    <p role="alert">{salesError}</p>
                    <button className="secondary" onClick={() => setSalesAttempt((attempt) => attempt + 1)}>Retry</button>
                  </div>
                ) : !report ? (
                  <p className="empty" role="status">Loading sales report…</p>
                ) : !report.payment_count && !report.refund_count ? (
                  <p className="empty">No payments or refunds in this period.</p>
                ) : (
                  <div className="chart tall">
                    <ResponsiveContainer
                      width="100%"
                      height="100%"
                    >
                      <AreaChart data={chart}>
                        <CartesianGrid
                          stroke="#eeeef4"
                          vertical={false}
                        />

                        <XAxis dataKey="day" />
                        <YAxis />

                        <Tooltip
                          formatter={(value) => money(value)}
                        />

                        <Area
                          type="monotone"
                          dataKey="sales"
                          name="Net sales"
                          dot={chart.length === 1}
                          stroke="#7357d9"
                          fill="#eee8ff"
                        />
                      </AreaChart>
                    </ResponsiveContainer>
                  </div>
                )}
              </div>
              {report?.enquiries && (
                <section className="panel settings-panel enquiry-conversion" aria-labelledby="enquiry-conversion-title">
                  <h3 id="enquiry-conversion-title">Enquiry conversion</h3>
                  <p>Enquiries received in this date range and their current follow-up status.</p>
                  <dl>
                    <div><dt>Received</dt><dd>{report.enquiries.received}</dd></div>
                    <div><dt>Linked to a customer</dt><dd>{report.enquiries.linked}</dd></div>
                    <div><dt>With an order</dt><dd>{report.enquiries.converted}</dd></div>
                    <div>
                      <dt>Conversion rate</dt>
                      <dd>{report.enquiries.received
                        ? (report.enquiries.converted / report.enquiries.received).toLocaleString("en-IN", {
                          style: "percent", maximumFractionDigits: 1,
                        })
                        : "—"}</dd>
                    </div>
                  </dl>
                </section>
              )}
            </>
          )}

          {/* WEBSITE BUILDER */}
          {page === "Website Builder" && !isSalesStaff && (
            <>
              <SectionTitle
                title="Website builder"
                desc={isWebsiteEditor ? "Update this business’s website drafts." : "Manage this business’s websites and local storefront links."}
              />

              <section className="panel settings-panel website-settings">
                <h3>Websites</h3>
                {activeWebsites.length > 0 && (
                  <label className="website-picker">
                    Edit website
                    <select
                      value={activeWebsite?.id ?? ""}
                      disabled={websiteBusy}
                      onChange={(event) => {
                        if (canLeaveWebsite()) openWebsite(Number(event.target.value));
                      }}
                    >
                      {!activeWebsite && <option value="" disabled>Select a website</option>}
                      {activeWebsites.map((site) => (
                        <option key={site.id} value={site.id}>
                          {site.label} · {site.published ? "Published" : "Draft"}
                        </option>
                      ))}
                    </select>
                  </label>
                )}
                {websites && activeWebsites.length === 0 && (
                  <p>{isWebsiteEditor ? "No websites are assigned to you. Ask the business owner to grant access."
                    : archivedWebsites.length ? "Restore an archived website or create a new one." : "Create your first website to open the editor."}</p>
                )}
                {websites && !isWebsiteEditor && (
                  <WebsiteLifecycle
                    selected={activeWebsite}
                    archived={archivedWebsites}
                    busy={websiteBusy}
                    setBusy={setWebsiteLifecycleBusy}
                    canLeaveWebsite={canLeaveWebsite}
                    onChange={applyWebsiteChange}
                  />
                )}
                {!websites && !websiteError && <p role="status">Loading websites…</p>}
                {websites && !isWebsiteEditor && (
                  <form className="workspace-form" onSubmit={addWebsite}>
                    <label>
                      New website name
                      <input value={websiteLabel} required maxLength={100} disabled={websiteBusy} onChange={(event) => setWebsiteLabel(event.target.value)} />
                    </label>
                    <button className="primary" disabled={websiteBusy || !websiteLabel.trim()}>
                      {creatingWebsite ? "Creating…" : "Create website"}
                    </button>
                  </form>
                )}
                {websiteError && <p role="alert">{websiteError}</p>}
                {!websites && websiteError && (
                  <button className="secondary" onClick={() => {
                    setWebsiteError("");
                    setWebsiteAttempt((attempt) => attempt + 1);
                  }}>Retry</button>
                )}
              </section>

              {activeWebsite && <div className="builder">
                <div className="panel editor">
                  <h3>Customize your storefront</h3>

                  <p>Update the preview without writing code.</p>

                  <label>
                    Business name

                    <input
                      maxLength={100}
                      disabled={!storefront || websiteBusy}
                      value={siteName}
                      onChange={(event) => editStorefront("name", event.target.value)}
                    />
                  </label>

                  <label>
                    Hero headline

                    <input
                      maxLength={200}
                      disabled={!storefront || websiteBusy}
                      value={siteHeadline}
                      onChange={(event) => editStorefront("headline", event.target.value)}
                    />
                  </label>

                  <label>
                    Accent color

                    <input
                      type="color"
                      disabled={!storefront || websiteBusy}
                      value={siteColor}
                      onChange={(event) => editStorefront("accent_color", event.target.value)}
                    />
                  </label>

                  <fieldset className="website-catalog" disabled={!storefront || websiteBusy}>
                    <legend>Website catalog</legend>
                    <label>
                      Products to show
                      <select
                        value={websiteProductIds === null ? "all" : "selected"}
                        onChange={(event) => editStorefront("product_ids", event.target.value === "all" ? null : [])}
                      >
                        <option value="all">All products</option>
                        <option value="selected">Selected products</option>
                      </select>
                    </label>
                    {websiteProductIds !== null && (
                      <>
                        {productLoad === "loading" && <p role="status">Loading products…</p>}
                        {productLoad === "error" && (
                          <div>
                            <p role="alert">Could not load the website catalog.</p>
                            <button className="secondary" type="button" onClick={() => {
                              setProductLoad("loading");
                              setLoadAttempt((attempt) => attempt + 1);
                            }}>Retry catalog</button>
                          </div>
                        )}
                        {productLoad === "ready" && products.length === 0 && <p>No products in this business’s catalog.</p>}
                        {productLoad === "ready" && products.length > 0 && (
                          <div className="website-product-list">
                            {products.map((product) => (
                              <label key={product.id} className="website-product-option">
                                <input
                                  type="checkbox"
                                  checked={selectedProductIds.has(product.id)}
                                  onChange={(event) => {
                                    const updated = event.target.checked
                                      ? [...websiteProductIds, product.id]
                                      : websiteProductIds.filter((id) => id !== product.id);
                                    editStorefront("product_ids", updated);
                                  }}
                                />
                                <span>{product.name} · {money(product.price)}</span>
                              </label>
                            ))}
                          </div>
                        )}
                      </>
                    )}
                  </fieldset>

                  <label className="website-product-option">
                    <input
                      type="checkbox"
                      disabled={!storefront || websiteBusy}
                      checked={websiteAcceptsInquiries}
                      onChange={(event) => editStorefront("accept_inquiries", event.target.checked)}
                    />
                    Show a contact form after publishing
                  </label>

                  <button
                    className="primary"
                    disabled={!storefront || websiteBusy}
                    onClick={saveDraft}
                  >
                    <CheckCircle2 size={16} />
                    {storefrontSaving ? "Saving…" : "Save draft"}
                  </button>

                  {!storefront && !storefrontLoadError && <p role="status">Loading draft…</p>}
                  {storefrontLoadError && (
                    <>
                      <p role="alert">{storefrontLoadError}</p>
                      <button className="secondary" onClick={() => {
                        setStorefrontLoadError("");
                        setStorefrontAttempt((attempt) => attempt + 1);
                      }}>
                        Retry
                      </button>
                    </>
                  )}
                  {storefrontSaveError && <p role="alert">{storefrontSaveError}</p>}
                  {storefrontSaveState === "saved" && <p className="saved" role="status">Draft saved.</p>}
                  {storefront && (
                    <div className="publication-controls">
                      <h3>Local storefront</h3>
                      {isWebsiteEditor ? (
                        <p>An owner or manager can publish your saved draft.</p>
                      ) : (
                        <>
                          <p>Publishing shares a snapshot of the saved draft and its chosen product names and prices.</p>
                          {storefrontSaveState === "edited" && <p>Save your edits before publishing.</p>}
                          <button
                            className="secondary"
                            disabled={websiteBusy || storefrontSaveState === "edited"}
                            onClick={() => changePublication()}
                          >
                            {publicationAction === "publishing" ? "Publishing…" : publication ? "Publish update" : "Publish locally"}
                          </button>
                        </>
                      )}
                      {publication && (
                        <>
                          <a className="text-button" href={`/store/${publication.slug}`} target="_blank" rel="noopener noreferrer">
                            Open storefront <ExternalLink size={14} />
                          </a>
                          {!isWebsiteEditor && <button
                            className="secondary"
                            disabled={websiteBusy}
                            onClick={() => changePublication(true)}
                          >
                            {publicationAction === "unpublishing" ? "Taking down…" : "Take down"}
                          </button>}
                        </>
                      )}
                      {publicationFeedback && (
                        <p role={publicationFeedback.error ? "alert" : "status"}>{publicationFeedback.message}</p>
                      )}
                    </div>
                  )}
                </div>

                <div className="panel storefront">
                  <div className="preview-bar">
                    <span>● ● ●</span>
                    Storefront preview
                    <ExternalLink size={14} />
                  </div>

                  <div className="store-header">
                    <strong>
                      {siteName || "Your Business"}
                    </strong>

                    <span>
                      Home　Shop　About　Contact
                    </span>
                  </div>

                  <div
                    className="store-hero"
                    style={{
                      background: `linear-gradient(
                        135deg,
                        ${siteColor}20,
                        #f8f5ff
                      )`,
                    }}
                  >
                    <div className="store-kicker">
                      NEW COLLECTION
                    </div>

                    <h2>
                      {siteHeadline || "Welcome to our store"}
                    </h2>

                    <p>
                      Thoughtfully curated products for every
                      occasion.
                    </p>

                    <span
                      className="store-button"
                      style={{ background: siteColor }}
                    >
                      Explore collection
                    </span>
                  </div>

                  <h4>Featured products</h4>

                  {productLoad === "ready" && websiteProducts.length === 0 && (
                    <p className="empty">No products are shown in this website’s draft.</p>
                  )}
                  <div className="store-products">
                    {websiteProducts.slice(0, 3).map((product) => (
                      <div key={product.id}>
                        <div className="store-product-img">
                          📦
                        </div>

                        <strong>{product.name}</strong>
                        <small>{money(product.price)}</small>
                      </div>
                    ))}
                  </div>
                </div>
              </div>}
              {!isWebsiteEditor && <WebsiteRequests onRefreshWebsites={() => {
                if (!websiteBusy) {
                  setWebsiteError("");
                  setWebsiteAttempt((attempt) => attempt + 1);
                }
              }} />}
            </>
          )}

          {page === "Website enquiries" && canManageBusiness && (
            <>
              <SectionTitle title="Website enquiries" desc="Review messages from your published websites and track follow-up." />
              <WebsiteInquiries
                customers={customers}
                orders={orders}
                canCreateOrders={orderLoad === "ready" && productLoad === "ready" && products.some((product) => product.stock > 0)}
                onCustomerCreated={(customer) => setCustomers((previous) => [
                  customer, ...(previous ?? []).filter((item) => item.id !== customer.id),
                ])}
                onNewOrder={(inquiry) => {
                  setOrderInquiry(inquiry);
                  setShowOrderForm(true);
                }}
                onOpenOrder={setDetailOrderId}
              />
            </>
          )}

          {/* AI ASSISTANT */}
          {page === "AI Assistant" && canManageBusiness && (
            <>
              <SectionTitle
                title="AI Business Assistant"
                desc="Ask about the records saved for your business."
              />

              <div className="chat-panel">
                <div className="chat-head">
                  <span className="ai-avatar">
                    <Sparkles size={19} />
                  </span>

                  <span>
                    <strong>Business Copilot</strong>

                    <small>Local, read-only answers</small>
                  </span>

                  {assistantHistory?.exchanges.length > 0 && (
                    <button
                      className="secondary"
                      type="button"
                      disabled={assistantDisabled || dictating}
                      onClick={deleteHistory}
                    >
                      {historyAction === "clearing" ? "Clearing…" : "Clear history"}
                    </button>
                  )}
                </div>

                <div className="chat-messages" role="log" aria-label="Assistant conversation" ref={chatLog}>
                  {!assistantHistory && !historyError && <p role="status">Loading saved conversation…</p>}
                  {assistantHistory?.older_before != null && (
                    <button
                      className="text-button"
                      type="button"
                      disabled={assistantDisabled || dictating}
                      onClick={loadOlderHistory}
                    >
                      {historyAction === "loading older" ? "Loading…" : "Load older messages"}
                    </button>
                  )}
                  {messages.map((item) => (
                    <div
                      className={"chat-row " + item.who}
                      key={item.id}
                    >
                      <div className="bubble">
                        <div lang={item.language ?? chatLanguage(item.text)}>{item.text}</div>
                        {item.who === "ai" && item.id !== "greeting" && (
                          <>
                            <button
                              className="text-button read-reply"
                              type="button"
                              disabled={dictating}
                              onClick={() => listen(item.id, item.text, item.language ?? chatLanguage(item.text))}
                            >
                              {playback?.index === item.id && !playback.error ? "Stop reading" : "Read aloud"}
                            </button>
                            {playback?.index === item.id && playback.error && (
                              <div role="status">{playback.error}</div>
                            )}
                          </>
                        )}
                      </div>
                    </div>
                  ))}
                  {assistantBusy && <p role="status">Checking your business records…</p>}
                </div>

                <div className="assistant-prompts" aria-label="Suggested questions">
                  {assistantPrompts.map((prompt) => (
                    <button
                      key={prompt}
                      className="secondary"
                      type="button"
                      disabled={assistantDisabled || dictating}
                      onClick={() => submitQuestion(prompt)}
                    >
                      {prompt}
                    </button>
                  ))}
                  {localizedAssistantPrompts.map(({ text, language }) => (
                    <button
                      key={text}
                      className="secondary"
                      type="button"
                      lang={language}
                      disabled={assistantDisabled || dictating}
                      onClick={() => submitQuestion(text)}
                    >
                      {text}
                    </button>
                  ))}
                </div>
                {assistantError && <p className="empty" role="alert">{assistantError}</p>}
                {historyError && (
                  <div className="empty">
                    <p role="alert">{historyError}</p>
                    {!assistantHistory && (
                      <button className="secondary" onClick={() => {
                        setHistoryError("");
                        setHistoryAttempt((previous) => previous + 1);
                      }}>Retry</button>
                    )}
                  </div>
                )}
                <AssistantComposer
                  message={message}
                  setMessage={setMessage}
                  disabled={assistantDisabled}
                  onSubmit={submitQuestion}
                  onStartDictation={stopReading}
                  onListeningChange={setDictating}
                />

                <div className="chat-note">
                  Ask about sales, stock, orders, or customer counts in English, Hindi, or Telugu.
                </div>
              </div>
            </>
          )}

          {/* SETTINGS */}
          {page === "Platform admin" && account.is_platform_admin && (
            <>
              <SectionTitle title="Platform admin" desc="View business accounts across this installation." />
              <PlatformBusinesses key={directoryVersion} />
              <WebsiteRequests platformAdmin onRefreshWebsites={() => setDirectoryVersion((version) => version + 1)} />
            </>
          )}
          {page === "Agencies" && (
            <>
              <SectionTitle title="Agencies" desc="Manage client businesses for your agency from one login." />
              <Agencies
                onOpenWorkspace={switchWorkspace}
                onWorkspacesChanged={() => {
                  setWorkspaceError("");
                  setWorkspaceAttempt((attempt) => attempt + 1);
                }}
              />
            </>
          )}
          {page === "Settings" && (
            <>
              <SectionTitle
                title="Workspace settings"
                desc={
                  "Manage your development environment " +
                  "and business configuration."
                }
              />

              <div className="panel settings-panel">
                <h3>Environment status</h3>

                <p>
                  This frontend runs locally. Check whether
                  your FastAPI backend is available.
                </p>

                <div className="setting-row">
                  <span>Backend health</span>

                  <strong>{backendStatus}</strong>

                  <button
                    className="secondary"
                    onClick={checkApi}
                  >
                    Check connection
                  </button>
                </div>

                <div className="setting-row">
                  <span>Business</span>
                  <strong>{account.business_name}</strong>
                  <button className="secondary" onClick={() => {
                    setWorkspaceError("");
                    setWorkspaceAttempt((attempt) => attempt + 1);
                  }}>Refresh workspace list</button>
                </div>

                <div className="setting-row">
                  <span>Signed in as</span>
                  <strong>{account.email}</strong>
                  <button className="secondary" disabled={signingOut || productBusy} onClick={endSession}>
                    Sign out
                  </button>
                </div>
                {signOutError && <p role="alert">{signOutError}</p>}

                <div className="setting-row">
                  <span>Data source</span>
                  <strong>Local SQLite</strong>
                </div>

                <div className="setting-row">
                  <span>AI, WhatsApp, payments</span>
                  <strong>Not configured</strong>
                </div>

                <div className="notice">
                  <ShieldCheck size={18} />

                  This starter is a demo foundation, not a
                  production-ready system. Do not store
                  real customer information yet.
                </div>
              </div>
              <WorkspaceSettings
                account={account}
                websites={websites}
                onWorkspaceCreated={() => {
                  setWorkspaceError("");
                  setWorkspaceAttempt((attempt) => attempt + 1);
                }}
              />
              {account.role === "owner" && <WorkspaceActivity />}
              {account.role === "owner" && <TeamInvitations />}
              {account.role === "owner" && <AgencyAccess account={account} websites={websites} />}
            </>
          )}
        </div>
      </main>

      {/* ADD PRODUCT MODAL */}
      {detailOrder && <OrderDetails order={detailOrder} onClose={() => setDetailOrderId(null)} />}

      {refundDraft && (
        <div className="modal-backdrop" onClick={() => !orderBusy && setRefundDraft(null)}>
          <form className="modal" onClick={(event) => event.stopPropagation()} onSubmit={recordRefund}>
            <div className="modal-title">
              <h3>Refund order #ORD-{refundDraft.order.id}</h3>
              <button type="button" disabled={orderBusy} aria-label="Close" onClick={() => setRefundDraft(null)}>
                <X />
              </button>
            </div>
            <p>Record a full refund of {money(refundDraft.order.amount_paise / 100)} issued outside Vyapari AI.</p>
            <label className="refund-stock">
              <input
                type="checkbox"
                checked={refundDraft.restock}
                disabled={orderBusy}
                onChange={(event) => setRefundDraft({ ...refundDraft, restock: event.target.checked })}
              />
              Return all items to stock
            </label>
            {refundError && <p role="alert">{refundError}</p>}
            <button className="primary" type="submit" disabled={orderBusy}>
              {orderBusy ? "Recording…" : "Record refund"}
            </button>
          </form>
        </div>
      )}

      {showOrderForm && (
        <OrderForm
          customers={customers}
          products={products.filter((product) => product.stock > 0)}
          inquiry={orderInquiry}
          onSave={onOrderSaved}
          onClose={() => {
            setShowOrderForm(false);
            setOrderInquiry(null);
          }}
        />
      )}

      {showRestock && canManageBusiness && (
        <RestockDialog items={productsToRestock} onClose={() => setShowRestock(false)} />
      )}

      {inventoryProduct && canManageBusiness && (
        <InventoryDialog
          key={inventoryProduct.id}
          product={inventoryProduct}
          onUpdate={(updated) => setProducts((previous) => previous.map((item) => item.id === updated.id ? updated : item))}
          onClose={() => setInventoryProductId(null)}
        />
      )}

      {showProductForm && (
        <div
          className="modal-backdrop"
          onClick={() => !productBusy && setShowProductForm(false)}
        >
          <form
            className="modal"
            onClick={(event) => event.stopPropagation()}
            onSubmit={saveProduct}
            style={{ maxHeight: "90vh", overflowY: "auto" }}
          >
            <div className="modal-title">
              <h3>{editingProductId === null ? "Add product" : "Edit product"}</h3>

              <button
                type="button"
                disabled={productBusy}
                onClick={() => setShowProductForm(false)}
                aria-label="Close"
              >
                <X />
              </button>
            </div>

            {["name", "category", "price", "stock", "low_stock_threshold", "restock_target"].map(
              (key) => (
                <label key={key}>
                  {key === "restock_target" ? "Target stock (optional)"
                    : key === "low_stock_threshold" ? "Low-stock threshold" : key[0].toUpperCase() + key.slice(1)}

                  <input
                    disabled={productBusy}
                    required={!["category", "restock_target"].includes(key)}
                    maxLength={key === "name" ? 200 : key === "category" ? 100 : undefined}
                    step={key === "price" ? "any" : undefined}
                    type={
                      ["price", "stock", "low_stock_threshold", "restock_target"].includes(key)
                        ? "number"
                        : "text"
                    }
                    min={
                      ["price", "stock", "low_stock_threshold", "restock_target"].includes(key)
                        ? "0"
                        : undefined
                    }
                    value={draft[key]}
                    onChange={(event) =>
                      setDraft({
                        ...draft,
                        [key]: event.target.value,
                      })
                    }
                  />
                  {key === "restock_target" && <small>Uses the low-stock threshold when left blank.</small>}
                </label>
              )
            )}

            {formError && <p role="alert">{formError}</p>}
            <button
              className="primary"
              type="submit"
              disabled={productBusy}
            >
              {productBusy
                ? "Saving…"
                : editingProductId === null ? "Save product" : "Save changes"}
            </button>
          </form>
        </div>
      )}
    </div>
  );
}

function Customers({ active, customers, setCustomers, orders, canDelete }) {
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [loadError, setLoadError] = useState("");
  const [actionError, setActionError] = useState("");
  const [formError, setFormError] = useState("");
  const [draft, setDraft] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    listCustomers(controller.signal)
      .then((items) => {
        if (!controller.signal.aborted) setCustomers(items);
      })
      .catch(() => {
        if (!controller.signal.aborted) setLoadError("Could not load customers. Check that FastAPI is running.");
      });
    return () => controller.abort();
  }, [loadAttempt, setCustomers]);

  function openForm(customer) {
    setFormError("");
    setDraft(customer ? { ...customer, phone: customer.phone ?? "" } : { name: "", email: "", phone: "" });
  }

  async function saveCustomer(event) {
    event.preventDefault();
    if (busy) return;

    setBusy(true);
    setFormError("");
    setActionError("");
    const values = {
      name: draft.name.trim(),
      email: draft.email.trim(),
      phone: draft.phone.trim(),
    };
    try {
      if (draft.id === undefined) {
        const customer = await createCustomer(values);
        setCustomers((previous) => [customer, ...previous]);
      } else {
        const customer = await updateCustomer(draft.id, values);
        setCustomers((previous) => previous.map((item) => (
          item.id === customer.id ? customer : item
        )));
      }
      setDraft(null);
    } catch (error) {
      setFormError(`Could not save customer. ${error.message}`);
    } finally {
      setBusy(false);
    }
  }

  async function removeCustomer(customer) {
    if (busy || !window.confirm(`Delete "${customer.name}"?`)) return;

    setBusy(true);
    setActionError("");
    try {
      await deleteCustomer(customer.id);
      setCustomers((previous) => previous.filter((item) => item.id !== customer.id));
    } catch (error) {
      setActionError(`Could not delete customer. ${error.message}`);
    } finally {
      setBusy(false);
    }
  }

  if (!active) return null;

  const totalsByCustomer = new Map();
  for (const order of orders ?? []) {
    if (order.status === "Cancelled") continue;
    const totals = totalsByCustomer.get(order.customer_id) ?? { count: 0, paidValue: 0 };
    totals.count += 1;
    if (order.paid_at && !order.refunded_at) totals.paidValue += order.amount_paise;
    totalsByCustomer.set(order.customer_id, totals);
  }

  return (
    <>
      <SectionTitle
        title="Customers"
        desc="Keep your customer relationships organized."
        action={
          <button className="primary" disabled={!customers || busy} onClick={() => openForm()}>
            <Plus size={17} />
            Add customer
          </button>
        }
      />
      <div className="panel">
        <div className="table-scroll">
          {actionError && <p className="empty" role="alert">{actionError}</p>}
          <table>
            <thead>
              <tr>
                <th>Customer</th>
                <th>Email</th>
                <th>Phone</th>
                <th>Orders</th>
                <th>Lifetime value</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {customers?.map((customer) => {
                const totals = totalsByCustomer.get(customer.id);
                return (
                <tr key={customer.id}>
                  <td>
                    <span className="avatar small-avatar">{customer.name[0]}</span>
                    <strong>{customer.name}</strong>
                  </td>
                  <td>{customer.email || "—"}</td>
                  <td>{customer.phone || "—"}</td>
                  <td>{orders ? (totals?.count ?? 0) : "—"}</td>
                  <td>{orders ? money((totals?.paidValue ?? 0) / 100) : "—"}</td>
                  <td>
                    <button
                      className="secondary"
                      disabled={busy}
                      aria-label={`Edit ${customer.name}`}
                      onClick={() => openForm(customer)}
                    >
                      Edit
                    </button>{" "}
                    {canDelete && <button
                      className="secondary"
                      disabled={busy}
                      aria-label={`Delete ${customer.name}`}
                      onClick={() => removeCustomer(customer)}
                    >
                      Delete
                    </button>}
                  </td>
                </tr>
                );
              })}
            </tbody>
          </table>
          {loadError ? (
            <div className="empty">
              <p role="alert">{loadError}</p>
              <button className="secondary" onClick={() => {
                setLoadError("");
                setLoadAttempt((attempt) => attempt + 1);
              }}>
                Retry
              </button>
            </div>
          ) : customers === null ? (
            <p className="empty" role="status">Loading customers…</p>
          ) : customers.length === 0 && (
            <p className="empty">No customers yet.</p>
          )}
        </div>
      </div>

      {draft && (
        <div className="modal-backdrop" onClick={() => !busy && setDraft(null)}>
          <form
            className="modal"
            onClick={(event) => event.stopPropagation()}
            onSubmit={saveCustomer}
          >
            <div className="modal-title">
              <h3>{draft.id === undefined ? "Add customer" : "Edit customer"}</h3>
              <button type="button" disabled={busy} aria-label="Close" onClick={() => setDraft(null)}>
                <X />
              </button>
            </div>
            <label>
              Name
              <input
                required
                maxLength={200}
                disabled={busy}
                value={draft.name}
                onChange={(event) => setDraft({ ...draft, name: event.target.value })}
              />
            </label>
            <label>
              Email (optional)
              <input
                type="email"
                maxLength={254}
                disabled={busy}
                value={draft.email}
                onChange={(event) => setDraft({ ...draft, email: event.target.value })}
              />
            </label>
            <label>
              Phone number (optional)
              <input
                type="tel"
                autoComplete="tel"
                maxLength={40}
                disabled={busy}
                value={draft.phone}
                onChange={(event) => setDraft({ ...draft, phone: event.target.value })}
              />
            </label>
            {formError && <p role="alert">{formError}</p>}
            <button className="primary" type="submit" disabled={busy}>
              {busy ? "Saving…" : "Save customer"}
            </button>
          </form>
        </div>
      )}
    </>
  );
}

export default App;
