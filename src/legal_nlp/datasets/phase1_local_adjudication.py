"""Generate a private, offline Phase-1 adjudication review page for one acórdão.

All original inputs and votes are reverified. Output is an HTML review *workspace*
and an explicit human proposal downloaded as JSON (never gold). No HTTP server,
remote URLs, CDN, external requests, database, or corpus mutation.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
from pathlib import Path

from ..io.jsonl import read_jsonl
from .phase1_evaluator_evidence import _verified_source_votes
from .phase1_source_lineage import audit_phase1_lineage
from .segmentation_overlap_components import _components
from .harmonized_label_support import _validate_and_load


def build_review_payload(snapshot, harmonized, taxonomy, raw_texts,
                         raw_annotations, ingested, sanitized, logical,
                         document_spans, document_id):
    audit = audit_phase1_lineage(snapshot, harmonized, taxonomy, raw_texts,
                                raw_annotations, ingested, sanitized, logical,
                                document_spans)
    votes = _verified_source_votes(raw_annotations, ingested)
    docs, rows, _, _, _ = _validate_and_load(snapshot, harmonized, taxonomy)
    doc = next((d for d in docs if d["document_id"] == document_id
                and d["phase"] == "phase_1"), None)
    if doc is None:
        raise ValueError("Phase-1 document ID not found in verified source")
    canonical_text = doc["text"]
    # Reconfirm text with ingested source, not merely a derived HTML copy.
    if not isinstance(canonical_text, str):
        raise ValueError("Missing verified document text")
    annotation_map = {
        a["annotation_id"]: a for a in read_jsonl(Path(ingested) / "annotations.jsonl")
    }
    regions = []
    candidate_rows = [r for r in rows if r["phase"] == "phase_1"
                      and r["document_id"] == document_id and r["task"] == "SEG"]
    for r in candidate_rows:
        if not (0 <= r["start"] < r["end"] <= len(canonical_text)):
            raise ValueError("Invalid region offsets")
        origins = []
        for source in r["provenance"]:
            aid = source["annotation_id"]
            if aid not in votes or aid not in annotation_map:
                raise ValueError("Broken evaluator provenance")
            source_ann = annotation_map[aid]
            individuals = []
            for reviewer, v in sorted(source_ann["reviewer_opinions"].items()):
                # The content is for a single user on the local machine.
                individuals.append({
                    "reviewer": reviewer,
                    "status": v["status"],
                    "comment": v.get("comment_raw") or "",
                })
            origins.append({
                "annotation_id": aid,
                "source_row": source_ann["source_row"],
                "annotator_id": source_ann.get("annotator_id"),
                "selection_status": source_ann["target_selection_status"],
                "review_agree_count": source_ann["review_agree_count"],
                "review_disagree_count": source_ann["review_disagree_count"],
                "original_label": source_ann["fields_original"].get("label"),
                "original_start": source_ann["fields_original"].get("start"),
                "original_end": source_ann["fields_original"].get("end"),
                "revised_label": source_ann["fields_revised"].get("label"),
                "revised_start": source_ann["fields_revised"].get("start"),
                "revised_end": source_ann["fields_revised"].get("end"),
                "votes": individuals,
            })
        regions.append({
            "id": r["region_id"], "label": r["label"],
            "source_label": r["source_label"],
            "start": r["start"], "end": r["end"],
            "origins": origins,
        })
    linked = []
    for label, spans in _components(candidate_rows):
        linked.append({
            "label": label,
            "ids": [s["region_id"] for s in spans],
            "start": min(s["start"] for s in spans),
            "end": max(s["end"] for s in spans),
        })
    all_ids = {r["id"] for r in regions}
    if len(all_ids) != len(regions):
        raise ValueError("Repeated region ID in source")
    return {
        "schema_version": "1.0.0",
        "mode": "local_human_adjudication_workspace_not_gold",
        "training_ready": False,
        "document_id": document_id,
        "text": canonical_text,
        "text_sha256": hashlib.sha256(canonical_text.encode("utf-8")).hexdigest(),
        "verified_raw_export_sha256": audit["verified_raw_export_sha256"],
        "regions": sorted(regions, key=lambda r: (r["start"], r["end"], r["label"], r["id"])),
        "overlap_families": sorted(linked, key=lambda g: (g["start"], g["end"], g["label"])),
        "note": "Private local review. Vote acceptance is not gold adjudication.",
    }


_PAGE = r"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Revisão estrutural local — Fase 1</title>
<style>
:root{font:15px system-ui,Segoe UI,sans-serif;color:#17212b;background:#eef2f7}
*{box-sizing:border-box}body{margin:0}header{background:#162637;color:#fff;padding:16px 22px}
header strong{font-size:19px}header small{display:block;color:#cad5e1;margin-top:5px}
main{display:grid;grid-template-columns:minmax(340px,38%) minmax(460px,1fr);gap:14px;padding:14px;align-items:start}
.panel{background:white;border:1px solid #d6dee8;border-radius:9px;padding:16px;min-width:0}
h2{font-size:17px;margin:0 0 12px}h3{font-size:15px}label{font-weight:650;display:block;margin:12px 0 5px}
select,input,textarea,button{font:inherit}select,input,textarea{width:100%;border:1px solid #a7b4c4;padding:9px;border-radius:5px;background:#fff}
textarea{min-height:76px}button{padding:9px 13px;border:0;border-radius:5px;cursor:pointer;background:#265c90;color:white}
button:disabled{background:#abb4bf;cursor:not-allowed}.muted{color:#556575;font-size:13px}
#text{white-space:pre-wrap;overflow-wrap:anywhere;font:13px/1.7 ui-monospace,Consolas,monospace;
max-height:75vh;overflow:auto;padding:12px;background:#f7f9fc;border:1px solid #dbe3ec;border-radius:6px}
mark{background:#fde69b;border-radius:2px;padding:1px 0;color:#17212b}
#items{max-height:40vh;overflow:auto}.item{border:1px solid #e0e6ef;border-radius:6px;padding:9px;margin:7px 0}
.item.active{border-color:#2874aa;background:#eaf4ff}.item button{float:right}
.source{background:#f3f6fb;border:1px solid #dce5ef;border-radius:6px;padding:10px;margin:8px 0}
.vote{margin:4px 0;white-space:pre-wrap;overflow-wrap:anywhere}
.warn{background:#fff1dd;border-left:4px solid #d49a30;padding:9px;margin:10px 0}
footer{margin:8px 14px 20px;color:#4e6274;font-size:12px}
@media(max-width:950px){main{display:block}.panel{margin-bottom:13px}}
</style></head>
<body><header><strong>Adjudicação de seções completas — Fase 1</strong>
<small id="source-note">Revisão local e privada • sem decisões gold automáticas</small></header>
<main>
<section class="panel"><h2>1. Evidência e candidatos</h2>
<label for="family">Família ou todas as regiões do documento</label>
<select id="family"></select>
<div id="counts" class="muted"></div>
<div id="items"></div>
<h3>Proveniência e avaliações</h3><div id="evidence" class="muted">Selecione uma região.</div>
</section>
<section class="panel">
<h2>2. Texto integral e proposta humana</h2>
<p class="muted">Os offsets são <code>[start,end)</code>. A visualização destaca a região selecionada; o texto permanece intacto.</p>
<div id="text"></div>
<div class="warn"><b>Revisão, não gold.</b> Delimitação mais longa ou aprovação por vários avaliadores não comprova seção completa. Verifique o início, o fim, a próxima seção e as regiões de outras labels.</div>
<label for="decision-label">Label da seção proposta</label><select id="decision-label"></select>
<div style="display:flex;gap:10px">
<div style="flex:1"><label for="start">Início</label><input id="start" type="number" min="0" step="1"></div>
<div style="flex:1"><label for="end">Fim exclusivo</label><input id="end" type="number" min="1" step="1"></div>
</div>
<label for="decision">Decisão humana</label>
<select id="decision"><option value="">Selecione explicitamente...</option>
<option value="propose_complete_section">Propor como seção completa</option>
<option value="fragment_or_internal">Fragmento/segmento interno; não eleger</option>
<option value="requires_further_review">Manter pendente</option></select>
<label for="reason">Justificativa com base no conteúdo e nas avaliações</label>
<textarea id="reason" placeholder="Explique os limites e o tratamento das propostas concorrentes."></textarea>
<label><input id="confirmed" type="checkbox" style="width:auto"> Conferi o trecho integral, os limites e os votos; esta é apenas uma proposta de revisão.</label>
<button id="add">Registrar proposta</button>
<h3>Propostas nesta sessão</h3><div id="decisions" class="muted">Nenhuma.</div>
<button id="export" disabled>Exportar JSON de revisão</button>
</section></main>
<footer>Uso local: não envie este HTML, seus comentários ou o JSON resultante para repositórios públicos.</footer>
<script id="dataset" type="application/json">__PAYLOAD__</script>
<script>
"use strict";
const data=JSON.parse(document.getElementById("dataset").textContent);
const $=(id)=>document.getElementById(id);
const decisions=[];
// Python offsets count Unicode code points, not JavaScript UTF-16 code units.
const textChars=Array.from(data.text);
let active=null;
const sortedFamilies=[...data.overlap_families];
const allFamily={label:"Todas as regiões",ids:data.regions.map(r=>r.id)};
const families=[allFamily,...sortedFamilies];
const regions=new Map(data.regions.map(r=>[r.id,r]));
const labels=[...new Set(data.regions.map(r=>r.label))].sort();
$("source-note").textContent=data.document_id+" | SHA-256 texto: "+data.text_sha256+" | somente local";
function option(parent,value,label){const el=document.createElement("option");el.value=value;el.textContent=label;parent.append(el)}
families.forEach((f,i)=>option($("family"),String(i),i===0?"Todas as regiões":f.label+" ["+f.start+","+f.end+") · "+f.ids.length+" regiões"));
labels.forEach(l=>option($("decision-label"),l,l));
const node=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n};
function textHighlight(region){
 const display=$("text");display.replaceChildren();
 if(!region){display.textContent=data.text;return}
 const s=region.start,e=region.end;
 display.append(document.createTextNode(textChars.slice(0,s).join("")));
 const mark=node("mark","",textChars.slice(s,e).join(""));mark.id="current-highlight";display.append(mark);
 display.append(document.createTextNode(textChars.slice(e).join("")));
 mark.scrollIntoView({block:"center",behavior:"instant"});
}
function showEvidence(region){
 const box=$("evidence");box.replaceChildren();
 box.append(node("p","muted",region.label+" ["+region.start+","+region.end+") · "+region.origins.length+" registro(s)-fonte"));
 for(const origin of region.origins){
  const wrap=node("div","source");wrap.append(node("b","",origin.annotator_id||"Anotador sem ID"));
  wrap.append(node("div","muted","Linha "+origin.source_row+" · "+origin.annotation_id+" · "+origin.selection_status));
  wrap.append(node("div","muted","Original: ["+origin.original_start+","+origin.original_end+") "+origin.original_label+" → revisado: ["+origin.revised_start+","+origin.revised_end+") "+origin.revised_label));
  for(const vote of origin.votes){
    if(vote.status==="not_recorded" && !vote.comment)continue;
    wrap.append(node("div","vote",vote.reviewer+": "+vote.status+(vote.comment?" | Comentário: "+vote.comment:"")));
  }
  box.append(wrap);
 }
}
function selectRegion(id){
 const region=regions.get(id);if(!region)throw Error("Região ausente");
 active=id;
 $("start").value=String(region.start);$("end").value=String(region.end);
 $("decision-label").value=region.label;
 textHighlight(region);showEvidence(region);renderRegions();
}
function renderRegions(){
 const family=families[Number($("family").value)||0];
 const ids=new Set(family.ids);
 const displayed=data.regions.filter(r=>ids.has(r.id));
 $("counts").textContent=displayed.length+" regiões · "+textChars.length+" caracteres no documento";
 const box=$("items");box.replaceChildren();
 displayed.forEach(r=>{
   const el=node("div","item"+(r.id===active?" active":""));
   const b=node("button","","Ver");b.type="button";b.addEventListener("click",()=>selectRegion(r.id));
   el.append(b,node("b","",r.label),node("div","muted","["+r.start+","+r.end+") · "+(r.end-r.start)+" caracteres · "+r.origins.length+" fonte(s)"));
   box.append(el);
 });
}
$("family").addEventListener("change",renderRegions);
$("add").addEventListener("click",()=>{
 const start=Number($("start").value),end=Number($("end").value),reason=$("reason").value.trim();
 const decision=$("decision").value,label=$("decision-label").value;
 if(!active){alert("Selecione uma região de origem para fundamentar a proposta.");return}
 if(!Number.isSafeInteger(start)||!Number.isSafeInteger(end)||start<0||end>textChars.length||start>=end){
   alert("Offsets inválidos para o documento de origem.");return
 }
 if(!decision||reason.length<20||!$("confirmed").checked){
   alert("Informe decisão, justificativa de pelo menos 20 caracteres e confirmação explícita.");return
 }
 if(decisions.some(d=>d.selected_source_region_id===active)){alert("Já há proposta para esta região; remova-a antes de registrar outra.");return}
 decisions.push({
    schema_version:"1.0.0",document_id:data.document_id,
    text_sha256:data.text_sha256,
    selected_source_region_id:active,
    proposed_label:label,proposed_start:start,proposed_end:end,
    disposition:decision,reason:reason,
    explicit_human_review_confirmed:true,
    status:"proposed_review_only_not_gold",training_ready:false
 });
 $("confirmed").checked=false;$("reason").value="";$("decision").value="";
 renderDecisions();
});
function renderDecisions(){
 const container=$("decisions");container.replaceChildren();
 for(const [index,entry] of decisions.entries()){
   const div=node("div","item");
   const remove=node("button","","Excluir");remove.addEventListener("click",()=>{decisions.splice(index,1);renderDecisions()});
   div.append(remove,node("b","",entry.proposed_label+" ["+entry.proposed_start+","+entry.proposed_end+")"));
   div.append(node("div","muted",entry.disposition+" · origem: "+entry.selected_source_region_id));
   container.append(div);
 }
 if(!decisions.length)container.textContent="Nenhuma.";
 $("export").disabled=decisions.length===0;
}
$("export").addEventListener("click",()=>{
 if(!decisions.length)return;
 const out={
   schema_version:"1.0.0",kind:"local_human_proposals_not_gold",
   document_id:data.document_id,text_sha256:data.text_sha256,
   verified_raw_export_sha256:data.verified_raw_export_sha256,
   training_ready:false,proposals:decisions
 };
 const blob=new Blob([JSON.stringify(out,null,2)],{type:"application/json;charset=utf-8"});
 const url=URL.createObjectURL(blob);
 const a=document.createElement("a");a.href=url;a.download="phase1_"+data.document_id.replace(/[^a-z0-9_-]/gi,"_")+"_review_proposals.json";
 document.body.append(a);a.click();a.remove();URL.revokeObjectURL(url);
});
$("family").value="0";renderRegions();textHighlight(null);
</script></body></html>"""


def write_review_html(payload, output):
    if payload.get("training_ready") is not False:
        raise ValueError("Only review-only payloads are allowed")
    output = Path(output)
    if output.exists():
        raise FileExistsError("Review page already exists; no silent overwriting")
    if not output.parent.is_dir():
        raise FileNotFoundError("Review page parent directory does not exist")
    # Prevent HTML/script escape from private legal text/comments:
    raw = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    page = _PAGE.replace("__PAYLOAD__", raw)
    output.write_text(page, encoding="utf-8")
    return {"document_id": payload["document_id"], "regions": len(payload["regions"]),
            "overlap_families": len(payload["overlap_families"]),
            "output": str(output), "training_ready": False}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ("snapshot","harmonized","raw-texts","raw-annotations","output"):
        p.add_argument("--"+name,type=Path,required=True)
    p.add_argument("--taxonomy",type=Path,default=Path("configs/labels.json"))
    p.add_argument("--ingested",type=Path,default=Path("data/interim/phase_1"))
    p.add_argument("--sanitized",type=Path,default=Path("data/interim/phase_1/sanitized"))
    p.add_argument("--logical",type=Path,default=Path("data/interim/phase_1/logical_spans"))
    p.add_argument("--document-spans",type=Path,default=Path("data/interim/phase_1/document_dataset/document_spans.jsonl"))
    p.add_argument("--document-id",default="phase_1:phase1:300")
    a=p.parse_args()
    payload=build_review_payload(a.snapshot,a.harmonized,a.taxonomy,
        a.raw_texts,a.raw_annotations,a.ingested,a.sanitized,a.logical,
        a.document_spans,a.document_id)
    print(json.dumps(write_review_html(payload,a.output),ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
