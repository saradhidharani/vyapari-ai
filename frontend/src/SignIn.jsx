import React, { useState } from "react";
import {
  completePasswordReset,
  completeSignup,
  setSessionToken,
  signIn,
  startPasswordReset,
  startSignup,
  verifySignIn,
  verifySignup,
} from "./api";

const titles = {
  signin: "Sign in",
  verify: "Verify your email",
  "signup-email": "Create a business account",
  "signup-code": "Check your email",
  "signup-details": "Set up your business",
  "reset-email": "Reset your password",
  "reset-code": "Choose a new password",
};

function CodeField({ value, onChange, disabled }) {
  return (
    <label>
      6-digit code
      <input
        name="code"
        inputMode="numeric"
        autoComplete="one-time-code"
        pattern="[0-9]{6}"
        maxLength={6}
        required
        disabled={disabled}
        value={value}
        onChange={(event) => onChange(event.target.value.replace(/\D/g, "").slice(0, 6))}
      />
      <small>The code expires in 10 minutes and works once.</small>
    </label>
  );
}

export default function SignIn({ onSignIn, sessionExpired }) {
  const [step, setStep] = useState("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [businessName, setBusinessName] = useState("");
  const [ticket, setTicket] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  function go(next) {
    setStep(next);
    setError("");
    setNotice("");
    setCode("");
    if (next === "signin" || next === "signup-email" || next === "reset-email") setPassword("");
  }

  function finish({ token, ...account }) {
    setSessionToken(token);
    onSignIn(account);
  }

  async function run(action) {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await action();
    } catch (failure) {
      setError(failure.message);
    } finally {
      setBusy(false);
    }
  }

  function sentNotice(result) {
    setNotice(`If ${result.destination} can receive email from us, a code is on its way. Check spam if it doesn't arrive.`);
  }

  async function attemptSignIn() {
    try {
      finish(await signIn(email.trim(), password));
    } catch (failure) {
      if (failure.detail?.code !== "verification_required") throw failure;
      setStep("verify");
      setCode("");
      setNotice(failure.message);
    }
  }

  function submit(event) {
    event.preventDefault();
    run(async () => {
      if (step === "signin") await attemptSignIn();
      else if (step === "verify") finish(await verifySignIn(email.trim(), password, code));
      else if (step === "signup-email") {
        sentNotice(await startSignup(email.trim()));
        setStep("signup-code");
      } else if (step === "signup-code") {
        setTicket((await verifySignup(email.trim(), code)).ticket);
        setNotice("");
        setStep("signup-details");
      } else if (step === "signup-details") finish(await completeSignup(ticket, password, businessName.trim()));
      else if (step === "reset-email") {
        sentNotice(await startPasswordReset(email.trim()));
        setStep("reset-code");
      } else if (step === "reset-code") finish(await completePasswordReset(email.trim(), code, password));
    });
  }

  function resend() {
    run(async () => {
      setCode("");
      if (step === "verify") await attemptSignIn();
      else if (step === "signup-code") sentNotice(await startSignup(email.trim()));
      else if (step === "reset-code") sentNotice(await startPasswordReset(email.trim()));
    });
  }

  const emailLocked = !["signin", "signup-email", "reset-email"].includes(step);
  const choosingPassword = step === "signup-details" || step === "reset-code";
  const submitLabel = {
    signin: "Sign in", verify: "Verify and sign in", "signup-email": "Send code", "signup-code": "Verify email",
    "signup-details": "Create business account", "reset-email": "Send code", "reset-code": "Reset password and sign in",
  }[step];

  return (
    <main className="modal-backdrop">
      <form className="modal" onSubmit={submit}>
        <div className="modal-title">
          <h1 style={{ fontSize: 22, margin: 0 }}>Vyapari AI</h1>
        </div>
        <h3>{titles[step]}</h3>
        {sessionExpired && step === "signin" && <p role="status">Your session ended. Sign in again.</p>}
        {step === "signup-details" && (
          <label>
            Business name
            <input autoComplete="organization" maxLength={100} required disabled={busy}
              value={businessName} onChange={(event) => setBusinessName(event.target.value)} />
          </label>
        )}
        <label>
          Email
          <input name="email" type="email" autoComplete="username" maxLength={254} required
            disabled={busy} readOnly={emailLocked} value={email} onChange={(event) => setEmail(event.target.value)} />
        </label>
        {(step === "signin" || choosingPassword) && (
          <label>
            {choosingPassword ? "New password" : "Password"}
            <input
              name="password"
              type="password"
              autoComplete={choosingPassword ? "new-password" : "current-password"}
              minLength={choosingPassword ? 12 : undefined}
              maxLength={128}
              required
              disabled={busy}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
            {choosingPassword && <small>Use at least 12 characters.</small>}
          </label>
        )}
        {(step === "verify" || step === "signup-code" || step === "reset-code") && (
          <CodeField value={code} onChange={setCode} disabled={busy} />
        )}
        {notice && <p role="status">{notice}</p>}
        {error && <p role="alert">{error}</p>}
        <button className="primary" type="submit" disabled={busy}>
          {busy ? "Please wait…" : submitLabel}
        </button>
        {(step === "verify" || step === "signup-code" || step === "reset-code") && (
          <button className="text-button" type="button" style={{ marginTop: 12 }} disabled={busy} onClick={resend}>
            Send a new code
          </button>
        )}
        {step === "signin" ? (
          <>
            <button className="text-button" type="button" style={{ marginTop: 16 }} disabled={busy} onClick={() => go("reset-email")}>
              Forgot password?
            </button>
            <button className="text-button" type="button" style={{ marginTop: 8 }} disabled={busy} onClick={() => go("signup-email")}>
              Create a business account
            </button>
          </>
        ) : (
          <button className="text-button" type="button" style={{ marginTop: 16 }} disabled={busy} onClick={() => go("signin")}>
            Back to sign in
          </button>
        )}
      </form>
    </main>
  );
}
