import html as _html
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import scipy.stats as st
from scipy.stats import binomtest
from sklearn.decomposition import PCA
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import StandardScaler

CAT_COLS = ["scanner_vendor", "contrast_phase", "slice_thickness_class", "sex", "age_band"]
CAT_LABEL = {"scanner_vendor": "Scanner brand mix", "contrast_phase": "Contrast phase mix",
             "slice_thickness_class": "Slice thickness mix", "sex": "Sex mix", "age_band": "Age mix"}


# ---------------------------------------------------------------- 1. reference profile
def fit_reference(ref, name="reference", n_pc=32, k=5):
    """Learn what 'normal' looks like from the hospital the model was validated on."""
    emb_cols = [c for c in ref if c.startswith("emb_")]
    E = ref[emb_cols].to_numpy()
    scaler = StandardScaler().fit(E)
    pca = PCA(min(n_pc, len(ref) - 1, len(emb_cols)), random_state=0).fit(scaler.transform(E))
    Xr = pca.transform(scaler.transform(E))
    nn = NearestNeighbors(n_neighbors=k + 1, metric="cosine").fit(Xr)
    d, _ = nn.kneighbors(Xr)
    return dict(
        name=name, n=len(ref), emb_cols=emb_cols, scaler=scaler, pca=pca, nn=nn, k=k,
        dist_thr=np.percentile(d[:, 1:].mean(axis=1), 95),
        cat={c: ref[c].fillna("MISSING").value_counts(normalize=True) for c in CAT_COLS},
        hu=ref["aorta_hu_mean"].dropna().to_numpy(),
        diam=ref["pred_max_diameter_mm"].dropna().to_numpy(),
        pred_aaa_rate=ref["pred_aaa"].astype(float).mean(),
        missing_meta=ref[CAT_COLS].isna().any(axis=1).mean(),
    )


def tvd(p, q):
    """Total variation distance between two category mixes (0 = identical, 1 = nothing in common)."""
    idx = p.index.union(q.index)
    return 0.5 * (p.reindex(idx, fill_value=0) - q.reindex(idx, fill_value=0)).abs().sum()


# ---------------------------------------------------------------- 2. the trigger list
def evaluate(new, prof):
    """Run every trigger on one batch of scans. Returns one row per trigger."""
    rows = []

    def add(group, trigger, value, yellow, red, meaning, action, kind="pct", worse="high", status=None):
        if value is None or pd.isna(value):
            s = "n/a"
        elif status:
            s = status
        elif worse == "high":
            s = "RED" if value > red else ("YELLOW" if value > yellow else "GREEN")
        else:
            s = "RED" if value < red else ("YELLOW" if value < yellow else "GREEN")
        rows.append(dict(group=group, trigger=trigger, value=value, yellow=yellow, red=red,
                         kind=kind, worse=worse, status=s, meaning=meaning, action=action))

    p = new["pred_aaa"].astype(float)

    # ---- A. What the model returns (needs no ground truth) ----
    G = "Model outputs (no ground truth needed)"
    add(G, "No-answer rate", p.isna().mean(), 0.02, 0.04,
        "The model returned no result for some scans.",
        "Ask the vendor why. Make sure staff treat a blank as 'review by hand', never as 'normal'.")
    add(G, "Change in share of scans called AAA", abs(p.mean() - prof["pred_aaa_rate"]), 0.05, 0.10,
        "The model flags a very different share of patients than at the reference hospital.",
        "Check whether your patients really differ (older, more aneurysms) or the model is drifting.", kind="pp")
    add(G, "Shift in predicted aorta size",
        st.wasserstein_distance(new["pred_max_diameter_mm"].dropna(), prof["diam"]) / prof["diam"].std(),
        0.25, 0.50, "Predicted aorta diameters look different from the reference hospital.",
        "Compare your patient mix with the validation data; recheck after any scanner change.", kind="sd")

    # ---- B. Patients and scanners ----
    G = "Patients and scanners"
    for c in CAT_COLS:
        add(G, CAT_LABEL[c], tvd(new[c].fillna("MISSING").value_counts(normalize=True), prof["cat"][c]),
            0.15, 0.30, f"The {CAT_LABEL[c].lower()} differs from what the model was validated on.",
            "Ask the vendor for results in the groups you have more of than the reference did.", kind="pct")
    add(G, "Shift in aorta brightness (HU)",
        st.wasserstein_distance(new["aorta_hu_mean"].dropna(), prof["hu"]) / prof["hu"].std(),
        0.25, 0.50, "Scans are brighter or darker than the validation data (usually a contrast or protocol change).",
        "Confirm the contrast protocol and scanner settings; watch accuracy on these scans.", kind="sd")

    # ---- C. Data quality and scan content ----
    G = "Data quality"
    add(G, "Rise in missing scanner/patient details",
        new[CAT_COLS].isna().any(axis=1).mean() - prof["missing_meta"], 0.05, 0.10,
        "More scans than usual are missing basic details such as scanner brand.",
        "Fix the data feed; missing details hide which scans the model struggles with.", kind="pct")

    if all(c in new for c in prof["emb_cols"]):
        E = new[prof["emb_cols"]].to_numpy()
        Xn = prof["pca"].transform(prof["scaler"].transform(E))
        d, _ = prof["nn"].kneighbors(Xn, n_neighbors=prof["k"])
        add(G, "Scans unlike anything in the reference", (d.mean(axis=1) > prof["dist_thr"]).mean(), 0.10, 0.20,
            "Many scans look unlike anything the model was validated on (the reference hospital sets this at 5%).",
            "Review a sample of these scans by hand; consider limiting the model to scans it has seen.")
        if len(new) >= 10:
            Z = StandardScaler().fit_transform(E)
            Z = Z / np.maximum(np.linalg.norm(Z, axis=1, keepdims=True), 1e-9)
            S = Z @ Z.T
            np.fill_diagonal(S, -1)
            twin, dup = S.argmax(axis=1), S.max(axis=1) > 0.95
            add(G, "Near-duplicate scans", dup.mean(), 0.01, 0.03,
                "The same patient seems to appear more than once (repeat scans or extra reconstructions).",
                "Remove repeats before measuring accuracy, otherwise results look better than they are.")
            if "patient_id" in new:
                pid = new["patient_id"].to_numpy(dtype=object)
                add(G, "Duplicates filed under different patient IDs", (dup & (pid != pid[twin])).mean(), 0.005, 0.02,
                    "Repeat scans are filed under different patient IDs, so ID-based checks will miss them.",
                    "Match patients by image similarity as well as by ID.")
    if "k_chi" in new and new["k_chi"].notna().any():
        m = new["k_chi"].notna()
        add(G, "Broken aorta 3D shapes", ((new.loc[m, "k_chi"] - 2).abs() > 0.1).mean(), 0.05, 0.15,
            "Some aorta outlines have holes or separate fragments, so measurements from them are unreliable.",
            "Review those segmentations before trusting their measurements.")

    # ---- D. Accuracy (only once the hospital has confirmed answers) ----
    # uses only the scans that have a confirmed answer, so a partly-labelled month does not break anything
    G = "Accuracy (needs confirmed answers)"
    if {"aaa", "max_aortic_diameter_mm"}.issubset(new.columns):
        lab = new[new["aaa"].notna() & new["max_aortic_diameter_mm"].notna()]
    else:
        lab = new.iloc[0:0]
    if len(lab):
        y = lab["aaa"].astype(bool).to_numpy()
        pv = lab["pred_aaa"].astype(float).to_numpy()
        pos = int(y.sum())
        if pos >= 3:
            tp = int((y & (pv == 1)).sum())
            sens = tp / pos
            hi = binomtest(tp, pos).proportion_ci(method="wilson").high
            s = "RED" if hi < 0.70 else ("YELLOW" if sens < 0.80 else "GREEN")
            add(G, "Aneurysms the model caught", sens, 0.80, 0.70,
                f"The model caught {tp} of {pos} known aneurysms.",
                "If this is red, stop relying on the AAA call and ask the vendor, then check how your hospital defines AAA.",
                worse="low", status=s)
        else:
            add(G, "Aneurysms the model caught", np.nan, 0.80, 0.70, "Fewer than 3 known aneurysms - too few to judge.", "Wait for more cases.")
        add(G, "Average diameter error", (lab["pred_max_diameter_mm"] - lab["max_aortic_diameter_mm"]).abs().mean(),
            2.0, 3.0, "The model's measurements are off by more than expected.",
            "Check scanner or protocol changes; compare against manual measurements.", kind="mm")
        add(G, "Labels that disagree with the 30 mm rule",
            ((lab["max_aortic_diameter_mm"] >= 30) != lab["aaa"].astype(bool)).mean(), 0.02, 0.05,
            "Your hospital calls aneurysms at a different size than the 30 mm rule the model follows.",
            "Agree one definition with the vendor before judging the model's AAA calls.")
        if "pred_aorta_dice" in lab:
            add(G, "Outline quality (Dice)", lab["pred_aorta_dice"].mean(), 0.90, 0.85,
                "The model's aorta outlines overlap the expert outlines less well than usual.",
                "Review a sample of outlines by eye.", kind="num2", worse="low")
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- 3. one-page report
COLORS = {"GREEN": "#2e9e5b", "YELLOW": "#e0a800", "RED": "#d64545", "n/a": "#9aa0a6"}


def fmt(v, kind):
    if pd.isna(v):
        return "-"
    return {"pct": f"{v:.1%}", "pp": f"{v * 100:.1f} pts", "mm": f"{v:.1f} mm",
            "sd": f"{v:.2f} SD", "num2": f"{v:.2f}"}[kind]


def build_report(res, hospital, month, n, ref_name):
    esc = _html.escape
    cnt = res["status"].value_counts()
    red, yel, grn = cnt.get("RED", 0), cnt.get("YELLOW", 0), cnt.get("GREEN", 0)
    if red:
        verdict, vc = f"Review needed before relying on this model here ({red} red alert{'s' if red > 1 else ''})", COLORS["RED"]
    elif yel:
        verdict, vc = f"Proceed with care and monitor ({yel} yellow alert{'s' if yel > 1 else ''})", COLORS["YELLOW"]
    else:
        verdict, vc = "Looks comparable to the validation hospital (no alerts)", COLORS["GREEN"]

    table = ""
    for g, sub in res.groupby("group", sort=False):
        table += f'<tr class="grp"><td colspan="4">{esc(g)}</td></tr>'
        for _, r in sub.iterrows():
            sign = ">" if r["worse"] == "high" else "<"
            lim = f'yellow {sign} {fmt(r["yellow"], r["kind"])}, red {sign} {fmt(r["red"], r["kind"])}'
            table += (f'<tr><td>{esc(r["trigger"])}</td><td>{fmt(r["value"], r["kind"])}</td>'
                      f'<td class="mut">{lim}</td><td><span class="dot" style="background:{COLORS[r["status"]]}"></span>'
                      f'{r["status"].title() if r["status"] != "n/a" else "n/a"}</td></tr>')

    todo = res[res["status"].isin(["RED", "YELLOW"])].copy()
    todo["o"] = todo["status"].map({"RED": 0, "YELLOW": 1})
    items = "".join(f'<li><b>{esc(r["trigger"])}</b> <span class="mut">({r["status"].lower()})</span>: '
                    f'{esc(r["meaning"])} <i>What to do:</i> {esc(r["action"])}</li>'
                    for _, r in todo.sort_values("o").iterrows()) or "<li>Nothing needs attention this month.</li>"

    small = (f'<p class="warn">Only {n} scans were checked, so treat these results as rough.</p>' if n < 50 else "")
    return f"""<html><head><meta charset="utf-8"><style>
body{{font-family:Helvetica,Arial,sans-serif;max-width:820px;margin:20px auto;color:#222;font-size:13px}}
h1{{font-size:20px;margin:0}} .sub{{color:#666;margin-bottom:10px}}
.verdict{{color:#fff;padding:10px 14px;border-radius:6px;font-size:15px;font-weight:bold;background:{vc}}}
table{{border-collapse:collapse;width:100%;margin:10px 0}} td{{padding:4px 6px;border-bottom:1px solid #eee}}
tr.grp td{{background:#f4f4f4;font-weight:bold}} .mut{{color:#777}} .dot{{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px}}
.warn{{background:#fff4d6;padding:6px 10px;border-radius:4px}} li{{margin-bottom:5px}} .foot{{color:#777;font-size:11px}}
@media print{{body{{margin:0}}}}</style></head><body>
<h1>AI aneurysm model: monitoring report</h1>
<div class="sub">{esc(hospital)} | {esc(str(month))} | {n} scans | compared with {esc(ref_name)}</div>
<div class="verdict">{esc(verdict)}</div>
<p>{grn} checks green, {yel} yellow, {red} red. Green means similar to the hospital the model was validated on.</p>
{small}<h3>What needs attention</h3><ul>{items}</ul>
<h3>All checks</h3><table>{table}</table>
<p class="foot">This is a screening aid, not a clinical or regulatory sign-off. Alert levels are starting points to be agreed
with the vendor and clinical team. With few scans (and few aneurysms) results are noisy.</p></body></html>"""


# ---------------------------------------------------------------- 4. the monthly step
def monthly_check(new, prof, hospital, month=None, out_dir="monitoring"):
    out = Path(out_dir)
    out.mkdir(exist_ok=True)
    month = month or date.today().strftime("%Y-%m")
    res = evaluate(new, prof)
    res.insert(0, "hospital", hospital)
    res.insert(1, "month", month)
    res.insert(2, "n_scans", len(new))
    hp = out / "history.csv"
    if hp.exists():
        h = pd.read_csv(hp)
        h = h[~((h["hospital"] == hospital) & (h["month"].astype(str) == str(month)))]
        res_all = pd.concat([h, res], ignore_index=True)
    else:
        res_all = res
    res_all.to_csv(hp, index=False)
    (out / f"report_{hospital}_{month}.html").write_text(build_report(res, hospital, month, len(new), prof["name"]))
    return res


def trend(hospital, out_dir="monitoring"):
    """Status of every trigger, month by month."""
    h = pd.read_csv(Path(out_dir) / "history.csv")
    return h[h["hospital"] == hospital].pivot(index="trigger", columns="month", values="status")
