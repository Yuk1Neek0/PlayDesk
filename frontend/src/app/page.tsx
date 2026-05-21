export default function BookingPage() {
  return (
    <div className="max-w-2xl mx-auto px-4 py-12">
      <h1 className="text-3xl font-bold text-gray-900 mb-2">Book a Station</h1>
      <p className="text-gray-500 mb-8">
        Manual booking flow — resource → date → time → confirm.
      </p>

      {/* Step 1: Choose resource */}
      <section className="bg-white rounded-lg shadow p-6 mb-6">
        <h2 className="text-lg font-semibold mb-4">1. Choose a Resource</h2>
        <div className="grid grid-cols-3 gap-3">
          {["PS5 Station", "Switch Station", "Private Room"].map((r) => (
            <button
              key={r}
              className="border rounded-lg p-4 text-sm font-medium hover:border-indigo-500 hover:bg-indigo-50 transition"
            >
              {r}
            </button>
          ))}
        </div>
      </section>

      {/* Step 2: Pick date */}
      <section className="bg-white rounded-lg shadow p-6 mb-6">
        <h2 className="text-lg font-semibold mb-4">2. Pick a Date</h2>
        <input
          type="date"
          className="border rounded px-3 py-2 w-full text-gray-700 focus:outline-none focus:ring-2 focus:ring-indigo-400"
          disabled
          placeholder="Date picker — coming soon"
        />
        <p className="text-xs text-gray-400 mt-2">
          (Placeholder — API wiring in Wave 1)
        </p>
      </section>

      {/* Step 3: Choose time slot */}
      <section className="bg-white rounded-lg shadow p-6 mb-6">
        <h2 className="text-lg font-semibold mb-4">3. Choose a Time Slot</h2>
        <div className="flex flex-wrap gap-2">
          {["10:00", "11:00", "12:00", "14:00", "15:00", "16:00", "18:00", "19:00", "20:00"].map(
            (t) => (
              <button
                key={t}
                className="border rounded px-3 py-1 text-sm hover:border-indigo-500 hover:bg-indigo-50 transition"
              >
                {t}
              </button>
            )
          )}
        </div>
        <p className="text-xs text-gray-400 mt-2">
          (Placeholder slots — availability API in Wave 1)
        </p>
      </section>

      {/* Step 4: Confirm */}
      <section className="bg-white rounded-lg shadow p-6">
        <h2 className="text-lg font-semibold mb-4">4. Confirm Booking</h2>
        <div className="space-y-3 text-sm text-gray-600 mb-6">
          <div className="flex justify-between">
            <span>Resource</span>
            <span className="font-medium text-gray-400">— not selected —</span>
          </div>
          <div className="flex justify-between">
            <span>Date</span>
            <span className="font-medium text-gray-400">— not selected —</span>
          </div>
          <div className="flex justify-between">
            <span>Time</span>
            <span className="font-medium text-gray-400">— not selected —</span>
          </div>
        </div>
        <button
          disabled
          className="w-full bg-indigo-600 text-white py-2 rounded font-medium opacity-50 cursor-not-allowed"
        >
          Confirm Booking
        </button>
      </section>
    </div>
  );
}
