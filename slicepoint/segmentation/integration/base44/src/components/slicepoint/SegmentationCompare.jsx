import React, { useState } from 'react';
import { getAccessToken } from '@base44/sdk';

export default function SegmentationCompare() {
  const [ct, setCt] = useState(null);
  const [vendor, setVendor] = useState(null);
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  async function submit(event) {
    event.preventDefault();
    setResult(null); setError('');
    if (!ct || !vendor) { setError('Choose both files.'); return; }
    if (ct.size + vendor.size > 50 * 1024 * 1024) { setError('Combined files must be under 50 MiB.'); return; }
    const accessToken = getAccessToken();
    if (!accessToken) { setError('Sign in before comparing masks.'); return; }
    const body = new FormData();
    body.append('ct', ct); body.append('vendor_mask', vendor);
    setBusy(true);
    try {
      const response = await fetch('/api/segmentation/compare', {
        method: 'POST', headers: { Authorization: `Bearer ${accessToken}` }, body,
        signal: AbortSignal.timeout(115_000),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Comparison failed.');
      setResult(data);
    } catch (err) {
      setError(err.name === 'TimeoutError' ? 'The comparison timed out. Please retry.' : err.message);
    } finally { setBusy(false); }
  }
  const colors = { high_agreement: 'border-green-600', review_with_caution: 'border-amber-500',
                   low_agreement: 'border-red-600', empty_mask_review: 'border-red-600' };
  return <section className="space-y-4 rounded-xl border p-6">
    <h2 className="text-xl font-semibold">Compare aorta segmentations</h2>
    <p>Upload a 3D CT and the vendor’s binary aorta mask on the same grid.</p>
    <p className="text-sm text-slate-600">Files pass through Base44 and Cloudflare to the comparison service on your computer. Temporary uploads are deleted after processing.</p>
    <form onSubmit={submit} className="space-y-4">
      <label className="block">CT volume (.nii.gz)
        <input type="file" accept=".nii.gz" disabled={busy} onChange={e => setCt(e.target.files?.[0] || null)} className="block" />
      </label>
      <label className="block">Vendor aorta mask (.nii.gz)
        <input type="file" accept=".nii.gz" disabled={busy} onChange={e => setVendor(e.target.files?.[0] || null)} className="block" />
      </label>
      <button type="submit" disabled={busy || !ct || !vendor} className="rounded bg-slate-900 px-4 py-2 text-white disabled:opacity-50">
        {busy ? 'Comparing…' : 'Compare segmentations'}
      </button>
    </form>
    {error && <p role="alert" className="text-red-700">{error}</p>}
    {result && <div className={`space-y-3 rounded-lg border-l-4 p-4 ${colors[result.assessment.status] || ''}`}>
      <p className="text-2xl font-semibold">Dice {result.metrics.dice.toFixed(3)} · {result.assessment.dice_percent}% agreement</p>
      <p>{result.assessment.message}</p>
      <img src={result.image.data_url} alt="CT slice with vendor and comparison-model aorta contours" className="w-full rounded" />
      <p className="text-sm text-slate-600">{result.assessment.interpretation}</p>
    </div>}
  </section>;
}
