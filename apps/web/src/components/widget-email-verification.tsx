"use client";
import { useState } from "react";
import { Row } from "@/lib/api";

export default function WidgetEmailVerification({ session, initialEmail }: {session: Row; initialEmail: string}) {
  const [email,setEmail]=useState(initialEmail),[challenge,setChallenge]=useState<Row|null>(null);
  const [code,setCode]=useState(""),[marketing,setMarketing]=useState(false),[verified,setVerified]=useState(false);
  const [busy,setBusy]=useState(false),[error,setError]=useState("");
  async function submit(event: React.FormEvent) {
    event.preventDefault();setBusy(true);setError("");
    try {
      const response=await fetch("/backend/v1/public/email/"+(challenge?"verify":"request"),{
        method:"POST",credentials:"omit",headers:{"Content-Type":"application/json",Authorization:"Bearer "+session.session_token},
        body:JSON.stringify(challenge?{challenge_id:challenge.challenge_id,code,marketing_opt_in:marketing}:{email}),
        signal:AbortSignal.timeout(10000),
      });
      const result=await response.json();
      if(!response.ok)throw Error(typeof result.detail==="string"?result.detail:"Email verification failed");
      if(challenge)setVerified(true);else setChallenge(result);
    }catch(error){setError((error as Error).message);}finally{setBusy(false);}
  }
  return <details className="panel-body"><summary>{verified?"Email verified":"Verify email for follow-up"}</summary>
    {verified?<p>Your email is verified{marketing?" and your email preference was saved":""}.</p>:<form onSubmit={submit} className="stack">
      <p>Your code stays in this form. Never send it in chat.</p>
      <label>Email for verification<input aria-label="Email for verification" type="email" required maxLength={254} disabled={!!challenge} value={email} onChange={event=>setEmail(event.target.value)}/></label>
      {challenge&&<><label>Email verification code<input aria-label="Email verification code" inputMode="numeric" autoComplete="one-time-code" required pattern="[0-9]{6}" maxLength={6} value={code} onChange={event=>setCode(event.target.value)}/></label>
        {challenge.consent_enabled&&<label><input type="checkbox" checked={marketing} onChange={event=>setMarketing(event.target.checked)}/>{challenge.consent_text}</label>}</>}
      <button className="btn" disabled={busy}>{busy?"Please wait…":challenge?"Verify email":"Send verification code"}</button>
      {challenge&&<button type="button" className="btn" disabled={busy} onClick={()=>{setChallenge(null);setCode("");setMarketing(false);}}>Change email or resend</button>}
      {error&&<p role="alert" className="error">{error}</p>}
    </form>}
  </details>;
}
