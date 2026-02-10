import React, { useEffect, useState } from "react";
import { supabase } from "./supabaseClient";

function App() {
  const [accidents, setAccidents] = useState([]);

  // Fetch accident data
  const fetchAccidents = async () => {
    const { data, error } = await supabase
      .from("accidents")
      .select("*")
      .order("timestamp", { ascending: false });

    if (!error) {
      setAccidents(data);
    }
  };

  // Update accident status (ambulance action)
  const updateStatus = async (id) => {
    await supabase
      .from("accidents")
      .update({ status: "RESPONDING" })
      .eq("id", id);

    fetchAccidents();
  };

  // Realtime listener
  useEffect(() => {
    fetchAccidents();

    const channel = supabase
      .channel("realtime-accidents")
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "accidents" },
        () => fetchAccidents()
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, []);

  return (
    <div style={{ padding: "20px" }}>
      <h2>🚨 IERAS – Accident Alerts</h2>

      {accidents.map((acc) => (
        <div
          key={acc.id}
          style={{
            border: "1px solid #ccc",
            padding: "10px",
            marginBottom: "10px",
          }}
        >
          <p><b>Camera:</b> {acc.camera_id}</p>
          <p><b>Severity:</b> {acc.severity}</p>
          <p><b>Status:</b> {acc.status}</p>

          {acc.video_url && (
            <a href={acc.video_url} target="_blank" rel="noreferrer">
              View Accident Clip
            </a>
          )}

          <br /><br />
          {acc.status === "PENDING" && (
            <button onClick={() => updateStatus(acc.id)}>
              🚑 Accept Emergency
            </button>
          )}
        </div>
      ))}
    </div>
  );
}

export default App;
