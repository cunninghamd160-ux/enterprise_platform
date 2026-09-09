import type { HeadcountRecord } from "../api/client";

export function RecordsTable({ records }: { records: HeadcountRecord[] }) {
  if (records.length === 0) {
    return <p className="text-sm text-slate-500">No records.</p>;
  }
  return (
    <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
      <table className="min-w-full divide-y divide-slate-200 text-sm">
        <thead className="bg-slate-50">
          <tr>
            <th className="px-4 py-3 text-left font-semibold text-slate-600">Team</th>
            <th className="px-4 py-3 text-left font-semibold text-slate-600">Month</th>
            <th className="px-4 py-3 text-right font-semibold text-slate-600">Headcount</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {records.map((record) => (
            <tr key={`${record.team}/${record.month}`} className="hover:bg-slate-50">
              <td className="px-4 py-2.5 font-medium text-slate-900">{record.team}</td>
              <td className="px-4 py-2.5 text-slate-600">{record.month}</td>
              <td className="px-4 py-2.5 text-right tabular-nums text-slate-900">{record.count}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
