"use client";
import {useEffect,useState} from "react";
import {api,command,Row,money} from "@/lib/api";

export default function WidgetProtection({base,installationId}:{base:string;installationId:string}) {
  const [value,setValue]=useState<Row|null>(null),[error,setError]=useState(""),[busy,setBusy]=useState(false);
  const path=base+"/installations/"+installationId+"/protection";
  useEffect(()=>{let active=true;api(path).then(result=>{if(active)setValue(result);}).catch(error=>{if(active)setError(error.message);});return()=>{active=false;};},[path]);
  async function save(event:React.SyntheticEvent) {
    event.preventDefault();event.stopPropagation();if(!value)return;setBusy(true);setError("");
    try {const fields=["daily_sessions","daily_turns","ip_daily_sessions","ip_daily_turns","monthly_spend_cap_minor","voice_max_seconds"];
      setValue(await command(path,Object.fromEntries(fields.map(key=>[key,Number(value[key])])),"PUT"));
    }catch(error){setError((error as Error).message);}finally{setBusy(false);}
  }
  return <details><summary>Visitor quotas and spending limit</summary>
    {error&&<p className="error" role="alert">{error}</p>}
    {value?<div className="stack">
      <p>Reserved {money(value.reserved_minor)} of {money(value.monthly_spend_cap_minor)} for {value.period} (UTC). Cost estimates are DRAFT. Owners receive alerts at 80% and 100%.</p>
      {([["daily_sessions","Sessions per day"],["daily_turns","Requests per day"],["ip_daily_sessions","Sessions per visitor IP per day"],["ip_daily_turns","Requests per visitor IP per day"],["monthly_spend_cap_minor","Monthly spending limit · paise (0 pauses requests)"],["voice_max_seconds","Maximum voice call · seconds"]] as const).map(([key,label])=>
        <label key={key}>{label}<input aria-label={label} type="number" min={key==="monthly_spend_cap_minor"?0:1} required value={value[key]} onChange={event=>setValue({...value,[key]:event.target.value})}/></label>)}
      <p className="field-note">Platform IP limits also apply. Production sessions require bot verification. Email is unverified until the visitor completes the email code form.</p>
      <button type="button" onClick={save} className="btn" disabled={busy}>{busy?"Saving…":"Save visitor protection"}</button>
    </div>:<p>Loading visitor protection…</p>}
  </details>;
}
