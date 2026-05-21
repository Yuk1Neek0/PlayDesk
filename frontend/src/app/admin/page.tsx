export default function AdminPage() {
  const mockBookings = [
    { id: 1, customer: "Alice Chen", resource: "PS5 Station", time: "2026-05-22 20:00", status: "confirmed", source: "agent" },
    { id: 2, customer: "Bob Kim", resource: "Private Room A", time: "2026-05-22 18:00", status: "confirmed", source: "manual" },
    { id: 3, customer: "Carol Wu", resource: "Switch Station", time: "2026-05-23 14:00", status: "pending", source: "agent" },
  ];

  const mockConversations = [
    { id: 1, customer: "alice-42", status: "active", messages: 6, started: "2026-05-22 19:45" },
    { id: 2, customer: "carol-99", status: "active", messages: 3, started: "2026-05-22 19:58" },
    { id: 3, customer: "dave-07", status: "ended", messages: 12, started: "2026-05-22 17:10" },
  ];

  return (
    <div className="max-w-5xl mx-auto px-4 py-12">
      <h1 className="text-3xl font-bold text-gray-900 mb-2">Staff Dashboard</h1>
      <p className="text-gray-500 mb-10">
        Live conversations and booking management — real-time wiring in Wave 1.
      </p>

      {/* Live conversations */}
      <section className="mb-10">
        <h2 className="text-xl font-semibold text-gray-800 mb-4">
          Live Conversations
          <span className="ml-2 text-xs font-normal text-green-600 bg-green-50 border border-green-200 px-2 py-0.5 rounded-full">
            {mockConversations.filter((c) => c.status === "active").length} active
          </span>
        </h2>
        <div className="bg-white rounded-lg shadow overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-gray-500 uppercase text-xs">
              <tr>
                <th className="px-4 py-3 text-left">ID</th>
                <th className="px-4 py-3 text-left">Customer</th>
                <th className="px-4 py-3 text-left">Status</th>
                <th className="px-4 py-3 text-left">Messages</th>
                <th className="px-4 py-3 text-left">Started</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {mockConversations.map((c) => (
                <tr key={c.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 font-mono text-gray-400">#{c.id}</td>
                  <td className="px-4 py-3 font-medium">{c.customer}</td>
                  <td className="px-4 py-3">
                    <span
                      className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium ${
                        c.status === "active"
                          ? "bg-green-50 text-green-700 border border-green-200"
                          : "bg-gray-100 text-gray-500"
                      }`}
                    >
                      {c.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-gray-600">{c.messages}</td>
                  <td className="px-4 py-3 text-gray-500">{c.started}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* All bookings */}
      <section>
        <h2 className="text-xl font-semibold text-gray-800 mb-4">All Bookings</h2>
        <div className="bg-white rounded-lg shadow overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-gray-500 uppercase text-xs">
              <tr>
                <th className="px-4 py-3 text-left">ID</th>
                <th className="px-4 py-3 text-left">Customer</th>
                <th className="px-4 py-3 text-left">Resource</th>
                <th className="px-4 py-3 text-left">Time</th>
                <th className="px-4 py-3 text-left">Status</th>
                <th className="px-4 py-3 text-left">Source</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {mockBookings.map((b) => (
                <tr key={b.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 font-mono text-gray-400">#{b.id}</td>
                  <td className="px-4 py-3 font-medium">{b.customer}</td>
                  <td className="px-4 py-3 text-gray-700">{b.resource}</td>
                  <td className="px-4 py-3 text-gray-500">{b.time}</td>
                  <td className="px-4 py-3">
                    <span
                      className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium ${
                        b.status === "confirmed"
                          ? "bg-green-50 text-green-700 border border-green-200"
                          : "bg-yellow-50 text-yellow-700 border border-yellow-200"
                      }`}
                    >
                      {b.status}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium ${
                        b.source === "agent"
                          ? "bg-indigo-50 text-indigo-700 border border-indigo-200"
                          : "bg-gray-100 text-gray-600"
                      }`}
                    >
                      {b.source}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="text-xs text-gray-400 mt-2">
          (Placeholder data — real-time API wiring in Wave 1)
        </p>
      </section>
    </div>
  );
}
