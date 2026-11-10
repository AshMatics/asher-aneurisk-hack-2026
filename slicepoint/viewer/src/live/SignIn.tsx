// Paste the service token once; the API answers with an HttpOnly session cookie.
// The input is uncontrolled: the token never enters React state, is never written to
// storage, and the field is cleared as soon as the form is submitted.
import { useRef, useState, type FormEvent } from "react";
import { Button, Card, Notice } from "../components/ui";
import { ApiError, type ApiClient } from "./client";

function signInMessage(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status === 401) return "That token was not accepted.";
    if (e.status === 429) return "Too many failed attempts from this address. Wait a minute and try again.";
    return e.message;
  }
  return "Sign-in failed.";
}

export function SignIn({ client, onSignedIn, notice }: { client: ApiClient; onSignedIn: () => void; notice?: string | null }) {
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const field = input.current;
    const token = field?.value.trim() ?? "";
    if (field) field.value = "";
    if (!token) {
      setError("Paste the service token.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await client.signIn(token);
      onSignedIn();
    } catch (err) {
      setError(signInMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto max-w-lg space-y-4">
      <h1 className="text-2xl font-semibold tracking-tight">Sign in to SlicePoint</h1>
      {notice ? <Notice tone="watch">{notice}</Notice> : null}
      <Card className="p-4">
        <form onSubmit={submit} className="space-y-3" noValidate>
          <label htmlFor="token" className="block text-sm font-medium">
            Service token
          </label>
          <input
            ref={input}
            id="token"
            type="password"
            autoComplete="off"
            spellCheck={false}
            className="h-10 w-full rounded-md border border-input bg-background px-3 font-mono text-sm"
          />
          <p className="text-xs text-muted-foreground">
            Ask whoever runs this service for the token. It is sent once to start a session and is not kept by this page; the
            browser holds only a session cookie that expires.
          </p>
          {error ? (
            <p role="alert" className="text-sm font-medium text-problem">
              {error}
            </p>
          ) : null}
          <Button type="submit" disabled={busy}>
            {busy ? "Signing in…" : "Sign in"}
          </Button>
        </form>
      </Card>
    </div>
  );
}
