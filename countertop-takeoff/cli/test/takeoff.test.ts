import { expect, test } from "bun:test"
import { Effect, Schema } from "effect"
import { createHash } from "node:crypto"
import { dirname, join, resolve } from "node:path"
import { fileURLToPath } from "node:url"
import { calculate, prepare, resolveSettings } from "../src/core"
import { decimal, rounded } from "../src/exact"
import { kernelLayer, Kernels } from "../src/kernels"
import { DrawInput, Job, Layout, LayoutInput, LegacyJob, PlanReply } from "../src/schema"
import { replay } from "../src/replay-core"
import { takeoff } from "../src/takeoff"
import { replyIssue } from "../src/validate"
import { assessment, facts, type Installation, job, layout, opening, rectangle, request, response, run, transport, withShape } from "./fixtures"

test("rect, L both sides and U expand exactly", async () => {
  const cases = [
    { shape: { kind: "rect", lengthIn: 60, depthIn: 24 }, area: 1440n, outline: rectangle(0,0,60,24) },
    { shape: { kind: "L", backIn: 120, sideIn: 72, depthIn: 24, side: "left" }, area: 4032n, outline: [[0,0],[120,0],[120,24],[24,24],[24,72],[0,72]] },
    { shape: { kind: "L", backIn: 120, sideIn: 72, depthIn: 24, side: "right" }, area: 4032n, outline: [[0,0],[120,0],[120,72],[96,72],[96,24],[0,24]] },
    { shape: { kind: "U", backIn: 120, leftIn: 72, rightIn: 84, depthIn: 24 }, area: 5472n, outline: [[0,0],[120,0],[120,84],[96,84],[96,24],[24,24],[24,72],[0,72]] },
  ] satisfies { shape: Installation["shape"]; area: bigint; outline: Layout["pieces"][number]["outline"] }[]
  for (const c of cases) {
    const p = await Effect.runPromise(prepare(withShape(c.shape)))
    expect(p.installations[0]?.outline).toEqual(c.outline)
    expect(p.installations[0]?.areaTicks).toBe(c.area * 256n)
  }
})

test("leg-relative centering and authorized estimates resolve without rounding", async () => {
  const shape = { kind: "U", backIn: 120, leftIn: 80, rightIn: 100, depthIn: 24 } satisfies Installation["shape"]
  for (const [leg, center, x, y] of [["back",60,50,4],["left",40,2,32],["right",50,98,42]] as const) {
    const symbolic = await Effect.runPromise(prepare(withShape(shape, [{ ...opening, at: { leg, centerFromStartIn: "center" } }])))
    const numeric = await Effect.runPromise(prepare(withShape(shape, [{ ...opening, at: { leg, centerFromStartIn: center } }])))
    expect(symbolic.kernelInstallations).toEqual(numeric.kernelInstallations)
    expect(symbolic.installations[0]?.cutouts[0]).toMatchObject({ x,y,w:20,h:16 })
  }
  const estimate = { fields: ["wIn", "at"], note: "Authorized synthetic estimate" } satisfies NonNullable<Installation["cutouts"][number]["estimate"]>
  const cutouts: Installation["cutouts"] = [{ ...opening, at: { leg: "main", centerFromStartIn: "center" }, estimate }]
  const j = withShape({ kind: "rect", lengthIn: 60, depthIn: 24 }, cutouts)
  expect((await Effect.runPromise(prepare(j))).geometryEstimates).toEqual([{ installationId:"island",cutoutIndex:0,...estimate,xIn:20,yIn:4,wIn:20,hIn:16 }])
  await expect(Effect.runPromise(prepare(withShape({kind:"rect",lengthIn:60.0625,depthIn:24},cutouts)))).rejects.toThrow("sixteenth-inch")
  const exact = withShape({kind:"rect",lengthIn:60.0625,depthIn:24},[{...opening,wIn:20.0625,at:{leg:"main",centerFromStartIn:"center"}}])
  expect((await Effect.runPromise(prepare(exact))).installations[0]?.cutouts[0]?.x).toBe(20)
  await expect(Effect.runPromise(prepare(withShape({kind:"outline",points:rectangle(0,0,60,24)},cutouts)))).rejects.toThrow("xIn and yIn")
  await expect(Effect.runPromise(prepare(withShape({kind:"rect",lengthIn:60,depthIn:24},[{...opening,at:{xIn:50,yIn:4}}])))).rejects.toThrow("outside")
})

test("v2 requires nullable facts, accepts sharp radius zero and rejects legacy settings", () => {
  const sharp = withShape({kind:"rect",lengthIn:60,depthIn:24},[{...opening,radiusMm:"0",at:{xIn:20,yIn:4}}])
  expect(Schema.decodeUnknownSync(Job)({...sharp,installations:sharp.installations.map(i=>({...i,insideCornerRadiusMm:"0"}))}).installations[0]?.cutouts[0]?.radiusMm).toBe("0")
  for (const invalid of [{...job,version:1},{...job,material:{...job.material,nominalThicknessMm:"0"}},{...job,settings:{minSeamToCutoutIn:3}}]) expect(() => Schema.decodeUnknownSync(Job,{onExcessProperty:"error"})(invalid)).toThrow()
  const {markupPercent:_missing,...material}=job.material
  expect(()=>Schema.decodeUnknownSync(Job)({...job,material})).toThrow()
})

test("exact gross SF, nominal purchased slabs and half-up invoice rounding", async () => {
  // 60*24/144 = 10 SF; 120*60/144 = 50 SF slab; 50*$10=$500.
  // $500/10=$50 material/SF; +$7.50 labor = $57.50; 10*$57.50=$575.
  const q=await run(takeoff(job))
  expect(q.totalSf).toBe("10.00"); expect(q.invoice[0]?.amount).toBe("575.00")
  expect(q.pricing).toEqual({materialCost:"500.00",markupPercent:"0",materialCharge:"500.00",materialRatePerSf:"50.00",laborPerSf:"7.50",ratePerSf:"57.50"})
  expect(rounded(decimal("1.005"))).toBe("1.01")
  const tiny=withShape({kind:"rect",lengthIn:1.0625,depthIn:1.0625})
  const r=response(await request(tiny))
  expect(calculate(tiny,await Effect.runPromise(prepare(tiny)),r).installations[0]?.areaSqIn).toBe("1.12890625")
  const precise={...job,installations:[{id:"a",label:"A",shape:{kind:"rect",lengthIn:1,depthIn:1},cutouts:[],...facts},{id:"b",label:"B",shape:{kind:"rect",lengthIn:1,depthIn:1},cutouts:[],...facts}]} satisfies Job
  const exact=calculate(precise,await Effect.runPromise(prepare(precise)),r)
  expect(exact.installations.map(i=>i.sf)).toEqual(["0.01","0.01"])
  expect(exact.totalSf).toBe("0.01"); expect(exact.pricing.materialRatePerSf).toBe("36000.00")
})

test("markup precedes rate rounding without marking up labor; null propagates", async () => {
  // 50 SF*$1.0011=$50.055; *1.125=$56.311875; /10=$5.6311875 -> $5.63.
  // Multiplying the already rounded $5.01 rate would wrongly yield $5.64.
  const marked={...job,material:{...job.material,pricePerSf:"1.0011",markupPercent:"12.5"}}
  const q=await run(takeoff(marked))
  expect(q.pricing).toEqual({materialCost:"50.06",markupPercent:"12.5",materialCharge:"56.31",materialRatePerSf:"5.63",laborPerSf:"7.50",ratePerSf:"13.13"})
  expect(q.invoice[0]?.amount).toBe("131.30")
  const blank=await run(takeoff({...marked,material:{...marked.material,markupPercent:null}}))
  expect(blank.pricing.materialCost).toBe("50.06"); expect(blank.pricing.materialCharge).toBeNull()
  expect(blank.pricing.laborPerSf).toBe("7.50"); expect(blank.invoice[0]?.amount).toBeNull()
  expect(blank.blanks.map(b=>b.field)).toEqual(["material.markupPercent"])
})

test("unresolved facts retain full geometry and independent labor, with one question per blank", async () => {
  const missing={...job,material:{name:null,vendor:null,pricePerSf:null,markupPercent:null,slab:null,profileId:null,profileProvenance:null,nominalThicknessMm:null},laborPerSf:null}
  const q=await run(takeoff(missing))
  expect(q.blanks).toHaveLength(9); expect(new Set(q.blanks.map(b=>b.field)).size).toBe(9)
  expect(q.totalSf).toBe("10.00"); expect(q.layout).toBeNull(); expect(q.invoice[0]?.amount).toBeNull()
  const original=withShape({kind:"rect",lengthIn:60,depthIn:24},[{...opening,at:{xIn:20,yIn:4},estimate:{fields:["at"],note:"Synthetic authorization"}}])
  const known={...original,material:{...original.material,profileId:null}}
  const partial=await run(takeoff(known))
  expect(partial.installations[0]).toMatchObject(original.installations[0] ?? {})
  expect(partial.geometryEstimates).toHaveLength(1); expect(partial.pricing.laborPerSf).toBe("7.50")
  expect(partial.pricing.materialCost).toBeNull(); expect(partial.material).toEqual(known.material)
})

test("only three stock settings default, and every default is disclosed", async () => {
  expect(resolveSettings(job).assumptions).toHaveLength(3)
  const explicit=resolveSettings({...job,settings:{slabTrimIn:0,allowRotate:false}})
  expect(explicit.assumptions.map(a=>a.setting)).toEqual(["kerfIn"]); expect(explicit.settings.allowRotate).toBe(false)
  const q=await run(takeoff(job)); expect(q.assumptions).toHaveLength(6)
  expect(q.assumptions.every(a=>a.note==="assumed, confirm with Dad")).toBe(true)
})

test("strict kernel replies and drawing path/domain errors fail at the boundary", async () => {
  for (const stdout of ['{"ok":true}','not json',JSON.stringify({...response(await request()),extra:true})]) {
    const e=await Effect.runPromise(takeoff(job).pipe(Effect.provide(kernelLayer(()=>Effect.succeed(stdout))),Effect.flip))
    expect(e._tag).toBe("KernelError"); expect(e.message).toContain("unreadable reply")
  }
  const r=await request(), draw:DrawInput={version:2,slab:r.slab,settings:r.settings,installations:r.installations,geometryEstimates:[],assessment:assessment(r),layout:null}
  for (const [stdout,message] of [['{"ok":true,"path":"wrong.png"}',"wrong place"],['{"ok":false,"error":{"tag":"DrawError","message":"Synthetic drawing failure"}}',"Synthetic drawing failure"]] as const) {
    const e=await Effect.runPromise(Kernels.use(k=>k.draw(draw,"preview.png",true)).pipe(Effect.provide(kernelLayer(()=>Effect.succeed(stdout))),Effect.flip))
    expect(e.message).toContain(message)
  }
})

test("assessment coherence rejects fabricated evidence, profile and proof", async () => {
  const r=await request(), good=response(r)
  expect(replyIssue(r,good)).toBeNull()
  const source={id:"S1",title:"Pinned manual",edition:"REV.03 02/2024",url:"https://assetstools.cosentino.com/api/v1/bynder/doc/0B425745-8BAC-4A87-9D7B54DA7AC39A1D/silestone-installation-manual.pdf",sha256:"56535666e6ed4e33ea1bc452968ea1b7922abd13c57d98fff40312c0aa24794a",filePages:[5],printedPages:[8],quotation:"Synthetic evidence fixture",interpretation:"Boundary identity fixture"} as const
  const c=good.assessment.checks[0]; if(!c) throw new Error("missing fixture")
  const sourced={...good,assessment:{...good.assessment,checks:[{...c,required:{value:"100",unit:"mm"},source}]}} satisfies PlanReply
  expect(replyIssue(r,sourced)).toBeNull()
  const invalid:PlanReply[]=[
    {...sourced,assessment:{...sourced.assessment,checks:[{...c,required:{value:"100",unit:"mm"},source:null}]}},
    {...good,assessment:{...good.assessment,profile:{...good.assessment.profile,id:"other"}}},
    {...good,assessment:{...good.assessment,search:{...good.assessment.search,status:"capped",limits:["time"]}}},
    {...sourced,assessment:{...sourced.assessment,checks:[{...c,source:{...source,sha256:"0".repeat(64)}}]}},
    {...good,assessment:{...good.assessment,status:"unresolved"}},
    {...good,assessment:{...good.assessment,conditions:[{id:"support",kind:"level-support",installationId:"island",cutoutIndex:null,joinId:null,status:"failed",source:null,explanation:"Failed supplied support",evidenceNote:"test",fields:[]}]}}
  ]
  for(const bad of invalid) expect(replyIssue(r,bad)).not.toBeNull()
  const conditional={...good,assessment:{...good.assessment,status:"conditional",conditions:[{id:"support",kind:"level-support",installationId:"island",cutoutIndex:null,joinId:null,status:"required-unverified",source,explanation:"Supply evidence",evidenceNote:null,fields:["installations[0].conditions"]}]}} satisfies PlanReply
  expect(replyIssue(r,conditional)).toBeNull()
  const q=calculate(job,await Effect.runPromise(prepare(job)),conditional)
  expect(q.pricing.materialCost).toBe("500.00"); expect(q.assessment.conditions).toEqual(conditional.assessment.conditions)
})

test("structural count evidence needs no manufacturer source; source dimensional evidence does", async () => {
  const r = await request(), good = response(r)
  const c = good.assessment.checks[0]
  if (!c) throw new Error("missing fixture")
  const counted = { ...good, assessment: { ...good.assessment, checks: [{ ...c, ruleId: "supplied-piece-count", operator: "=", actual: { value: "1", unit: "count" }, required: { value: "1", unit: "count" }, source: null }] } } satisfies PlanReply
  expect(replyIssue(r, counted)).toBeNull()
  expect(replyIssue(r, { ...counted, assessment: { ...counted.assessment, checks: [{ ...c, ruleId: "opening-rear-strip", operator: ">=", actual: { value: "101.6", unit: "mm" }, required: { value: "100", unit: "mm" }, source: null }] } })).toContain("source")
})

test("assess can assess the original subset without stock, while still asking for slab dimensions", async () => {
  const r: LayoutInput = { ...await request(), phase: "assess", slab: null }
  const a = assessment(r)
  const partial: PlanReply = { ok: true, version: 2, assessment: { ...a, status: "assessed" }, layout: null }
  expect(replyIssue(r, partial)).toBeNull()
  expect(replyIssue(r, { ...partial, assessment: { ...partial.assessment, unresolved: [] } })).toContain("question")
  expect(replyIssue({ ...r, phase: "plan" }, partial)).not.toBeNull()
})

function splitLayout(): Layout {
  return {...layout,pieces:[{id:"a",installationId:"island",outline:rectangle(0,0,30,24),cutouts:[{cutoutIndex:0,outline:rectangle(20,4,30,20)}]},
    {id:"b",installationId:"island",outline:rectangle(30,0,70,24),cutouts:[{cutoutIndex:0,outline:rectangle(30,4,40,20)}]},
    {id:"c",installationId:"island",outline:rectangle(70,0,100,24),cutouts:[]}],
    joins:[{id:"opening",installationId:"island",pieceIds:["a","b"],kind:"inside-opening",axis:"x",offsetIn:30,startIn:0,endIn:24,segments:[{x0:30,y0:0,x1:30,y1:4},{x0:30,y0:20,x1:30,y1:24}],cutoutIndex:0,origin:"supplied",reason:"supplied-join"},
      {id:"solid",installationId:"island",pieceIds:["b","c"],kind:"solid",axis:"x",offsetIn:70,startIn:0,endIn:24,segments:[{x0:70,y0:0,x1:70,y1:24}],cutoutIndex:null,origin:"automatic",reason:"stock-fit"}],
    slabs:[{index:1,placements:[{pieceId:"a",x:0,y:0,quarterTurns:0},{pieceId:"b",x:30.25,y:0,quarterTurns:0},{pieceId:"c",x:70.5,y:0,quarterTurns:0}]}]}
}
test("opening-center pins a join without imposing two pieces; explicit count remains exact", async () => {
  const j:Job={...job,installations:[{id:"island",label:"Island",shape:{kind:"rect",lengthIn:100,depthIn:24},cutouts:[{...opening,at:{xIn:20,yIn:4}}],...facts,sourceArrangement:{kind:"rectangular-run",axis:"x",rear:"min",provenance:"Confirmed synthetic datum"},seam:{kind:"opening-center",cutoutIndex:0}}]}
  const r=await request(j), l=splitLayout()
  expect(replyIssue(r,response(r,l))).toBeNull()
  const count={...r,installations:r.installations.map(i=>({...i,requiredPieceCount:2}))}
  expect(replyIssue(count,response(count,l))).toContain("count")
  const legacy={...j,installations:j.installations.map(i=>({...i,seam:{kind:"center-through-cutout",cutoutIndex:0}}))} satisfies Job
  await expect(Effect.runPromise(prepare(legacy))).rejects.toThrow("centered along")
  const wrong={...l,joins:l.joins.map(x=>x.id==="opening"?{...x,origin:"automatic" as const}:x)}
  expect(replyIssue(r,response(r,wrong))).toContain("supplied")
  for(const bad of [{...l,joins:[]},{...l,pieces:l.pieces.map(p=>({...p,cutouts:[]}))},
    {...l,joins:l.joins.map(x=>({...x,segments:[{x0:x.offsetIn,y0:0,x1:x.offsetIn,y1:24}]}))},
    {...l,slabs:[{index:1,placements:l.slabs[0]?.placements.map(p=>({...p,x:0}))??[]}]}]) expect(replyIssue(r,response(r,bad))).not.toBeNull()
})

test("concave pieces use rigid quarter turns; disconnected stone is rejected", async () => {
  const j={...withShape({kind:"L",backIn:60,sideIn:48,depthIn:12,side:"left"}),material:{...job.material,slab:{lengthIn:54,widthIn:64}}}
  const r=await request(j), outline=r.installations[0]?.outline; if(!outline) throw new Error("missing outline")
  const l={...layout,pieces:[{id:"p1",installationId:"island",outline,cutouts:[]}],slabs:[{index:1,placements:[{pieceId:"p1",x:0,y:0,quarterTurns:1}]}]} satisfies Layout
  expect(replyIssue(r,response(r,l))).toBeNull()
  expect(replyIssue({...r,settings:{...r.settings,allowRotate:false}},response(r,l))).toContain("rotation")
  const broken=await request(withShape({kind:"rect",lengthIn:60,depthIn:24},[{...opening,wIn:2,hIn:24,at:{xIn:29,yIn:0}}]))
  const disconnected={...layout,pieces:[{id:"p1",installationId:"island",outline:rectangle(0,0,60,24),cutouts:[{cutoutIndex:0,outline:rectangle(29,0,31,24)}]}]}
  expect(replyIssue(broken,response(broken,disconnected))).toContain("disconnected")
})

test("replay restores historical defaults and assumptions, including without a slab",async()=>{
  const {profileId:_id,profileProvenance:_provenance,nominalThicknessMm:_thickness,...material}=job.material
  for (const slab of [material.slab, null]) {
    const old=Schema.decodeUnknownSync(LegacyJob)({version:1,material:{...material,slab},laborPerSf:job.laborPerSf,settings:{},installations:[{id:"island",label:"Island",shape:{kind:"rect",lengthIn:60,depthIn:24},cutouts:[]}]})
    const layer=kernelLayer((name,args,stdin)=>{
      if(name!=="layout")return transport(name,args,stdin)
      const input=Schema.decodeUnknownSync(LayoutInput)(JSON.parse(stdin))
      expect(input.mode).toBe("geometry-replay");expect(input.material.profileId).toBeNull()
      expect(input.legacySettings).toEqual({minSeamToCutoutIn:6,minMaterialBesideCutoutIn:3})
      const a=assessment(input)
      return Effect.succeed(JSON.stringify({ok:true,version:2,assessment:{...a,checks:[],limitations:["geometry-replay"]},layout:slab === null ? null : layout}))
    })
    const q=await Effect.runPromise(replay(old).pipe(Effect.provide(layer)))
    expect(q.developmentOnly).toBe("geometry-replay-unassessed");expect(q.assessment.status).toBe("unresolved")
    expect(q.assessment.search.status).toBe("not-run")
    expect(q.pricing.materialCost).toBe(slab === null ? null : "500.00")
    expect(q.assumptions.filter(a=>a.setting.startsWith("min"))).toEqual([
      {setting:"minSeamToCutoutIn",value:"6",note:"assumed, confirm with Dad"},
      {setting:"minMaterialBesideCutoutIn",value:"3",note:"assumed, confirm with Dad"},
    ])
    const explicit=await Effect.runPromise(replay({...old,settings:{minSeamToCutoutIn:6,minMaterialBesideCutoutIn:3}}).pipe(Effect.provide(layer)))
    expect(explicit.assumptions.some(a=>a.setting.startsWith("min"))).toBe(false)
  }
})

test("only explicitly marked replay can retain an unassessed legacy layout; geometry checks still run", async () => {
  const r: LayoutInput = {...await request(),mode:"geometry-replay",material:{profileId:null,profileProvenance:null,nominalThicknessMm:null},legacySettings:{minSeamToCutoutIn:6,minMaterialBesideCutoutIn:3}}
  const a=assessment(r)
  const historical: PlanReply={ok:true,version:2,assessment:{...a,checks:[],limitations:["geometry-replay-unassessed"]},layout}
  expect(replyIssue(r,historical)).toContain("marker")
  expect(replyIssue(r,historical,"geometry-replay-unassessed")).toBeNull()
  expect(replyIssue(r,{...historical,assessment:{...historical.assessment,limitations:[]}},"geometry-replay-unassessed")).toContain("unassessed")
  expect(replyIssue(r,{...historical,layout:{...layout,slabs:[]}},"geometry-replay-unassessed")).not.toBeNull()
  const normal=await request()
  const unrun=assessment({...normal,phase:"assess"})
  expect(replyIssue(normal,{ok:true,version:2,assessment:unrun,layout})).toContain("search limits")
  expect(replyIssue(normal,{ok:true,version:2,assessment:unrun,layout},"geometry-replay-unassessed")).toContain("marker")
})

test("committed standalone bundle matches source",async()=>{
  const cli=resolve(dirname(fileURLToPath(import.meta.url)),"..")
  const built=await Bun.build({entrypoints:[join(cli,"src/main.ts")],target:"bun",minify:true});expect(built.success).toBe(true)
  const out=built.outputs[0];if(!out)throw new Error("Build omitted bundle")
  const digest=(s:string)=>createHash("sha256").update(s.replaceAll("\r\n","\n")).digest("hex")
  expect(digest(await Bun.file(join(cli,"takeoff.js")).text())).toBe(digest(await out.text()))
})
