export default function ChatPage() {
  return (
    <div className="max-w-2xl mx-auto px-4 py-12 flex flex-col" style={{ height: "calc(100vh - 56px)" }}>
      <h1 className="text-3xl font-bold text-gray-900 mb-1">AI Front Desk</h1>
      <p className="text-gray-500 mb-6">
        Chat with our AI to check availability, ask questions, and make bookings.
      </p>

      {/* Chat transcript */}
      <div className="flex-1 bg-white rounded-lg shadow p-4 overflow-y-auto mb-4 space-y-4">
        {/* Assistant greeting */}
        <div className="flex gap-3">
          <div className="w-8 h-8 rounded-full bg-indigo-600 flex items-center justify-center text-white text-xs font-bold shrink-0">
            AI
          </div>
          <div className="bg-gray-100 rounded-lg px-4 py-2 text-sm text-gray-800 max-w-sm">
            Hi! I&apos;m the PlayDesk AI front desk. I can help you check
            availability, answer questions about our game lounge, and make
            bookings. How can I help you today?
          </div>
        </div>

        {/* Placeholder tool-call hint */}
        <div className="flex gap-3 justify-end">
          <div className="bg-indigo-50 border border-indigo-100 rounded-lg px-4 py-2 text-sm text-indigo-700 max-w-sm">
            Is the PS5 room free on Saturday at 8pm?
          </div>
          <div className="w-8 h-8 rounded-full bg-gray-300 flex items-center justify-center text-gray-600 text-xs font-bold shrink-0">
            You
          </div>
        </div>

        {/* Tool-call in-flight hint */}
        <div className="flex gap-3">
          <div className="w-8 h-8 rounded-full bg-indigo-600 flex items-center justify-center text-white text-xs font-bold shrink-0">
            AI
          </div>
          <div className="space-y-1">
            <span className="inline-block text-xs text-gray-400 italic px-2 py-1 bg-gray-50 rounded border">
              checking availability…
            </span>
            <div className="bg-gray-100 rounded-lg px-4 py-2 text-sm text-gray-800 max-w-sm">
              The PS5 station is available Saturday at 8pm for up to 3 hours.
              Shall I book it for you?
            </div>
          </div>
        </div>

        <p className="text-center text-xs text-gray-400 mt-4">
          (Placeholder transcript — streaming AI integration in Wave 1)
        </p>
      </div>

      {/* Input bar */}
      <div className="flex gap-2">
        <input
          type="text"
          disabled
          placeholder="Type a message… (coming in Wave 1)"
          className="flex-1 border rounded-lg px-4 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400 disabled:bg-gray-100 disabled:text-gray-400"
        />
        <button
          disabled
          className="bg-indigo-600 text-white px-5 py-2 rounded-lg font-medium text-sm opacity-50 cursor-not-allowed"
        >
          Send
        </button>
      </div>
    </div>
  );
}
