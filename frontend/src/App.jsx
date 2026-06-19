import { useEffect, useState } from "react";
function App() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [lastUpdated, setLastUpdated] = useState(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [selectedMachine, setSelectedMachine] = useState(null);
  const [historyData, setHistoryData] = useState([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  useEffect(() => {
    const fetchData = () => {
      setIsRefreshing(true);
      fetch("http://127.0.0.1:8000/api/oee/daily/latest")
        .then((res) => {
          if (!res.ok) {
            throw new Error(`API Error ${res.status}`);
          }
          return res.json();
        })
        .then((json) => {
          setData(json);
          setError("");
          setLastUpdated(new Date());
        })
        .catch((err) => {
          console.error(err);
          setError(err.message);
        })
        .finally(() => {
          setIsRefreshing(false);
        });
    };
    fetchData();
    const interval = setInterval(fetchData, 10000);
    return () => clearInterval(interval);
  }, []);
  const openMachineHistory = (machineName) => {
    setSelectedMachine(machineName);
    setHistoryLoading(true);
    setHistoryData([]);
    fetch(
      `http://127.0.0.1:8000/api/downtime/history/${machineName}?production_date=${data.production_date}`
    )
      .then((res) => res.json())
      .then((json) => {
        setHistoryData(json.history || []);
      })
      .catch((err) => {
        console.error(err);
      })
      .finally(() => {
        setHistoryLoading(false);
      });
  };
  const closeHistory = () => {
    setSelectedMachine(null);
    setHistoryData([]);
  };
  const formatDate = (dateString) => {
    if (!dateString) return "";
    const date = new Date(dateString);
    return date.toLocaleDateString("en-GB", {
      day: "numeric",
      month: "long",
      year: "numeric",
    });
  };
  const formatTime = (date) => {
    if (!date) return "-";
    return date.toLocaleTimeString("en-GB", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  };
  if (!data && error) {
    return (
      <div className="page">
        <h2>Error</h2>
        <p>{error}</p>
      </div>
    );
  }
  if (!data) {
    return (
      <div className="page loading-page">
        <div className="spinner"></div>
        <h2>Loading Dashboard...</h2>
      </div>
    );
  }
  return (
    <div className="page">
      <div className="top-status">
        <div className="live-dot"></div>
        <span>Live</span>
        <span className="separator">|</span>
        <span>Last Updated: {formatTime(lastUpdated)}</span>
        <span className="separator">|</span>
        <span className={isRefreshing ? "refreshing active" : "refreshing"}>
          {isRefreshing ? "Refreshing..." : "Auto refresh every 10 sec"}
        </span>
      </div>
      <h1 className="title">INNOVIZ OEE Daily Dashboard</h1>
      <h3 className="date-title">
        Production Date: {formatDate(data.production_date)}
      </h3>
      {error && (
        <div className="warning-box">
          API Warning: {error}
        </div>
      )}
      <div className="card-grid">
        {data.machines.map((m) => {
          const statusColor = m.status === "PASS" ? "#28a745" : "#dc3545";
          return (
            <div
              key={m.machine}
              className="card clickable-card"
              onClick={() => openMachineHistory(m.machine)}
              style={{
                borderTop: `8px solid ${statusColor}`,
              }}
            >
              <h2 className="machine-name">{m.machine}</h2>
              <h1
                className="oee-value"
                style={{
                  color: statusColor,
                }}
              >
                {m.oee}%
              </h1>
              <p>
                <b>Target OEE:</b> {m.target_oee}%
              </p>
              <p>
                <b>Status:</b>{" "}
                <span
                  style={{
                    color: statusColor,
                    fontWeight: "bold",
                  }}
                >
                  {m.status}
                </span>
              </p>
              <p>
                <b>Availability:</b> {m.availability}%
              </p>
              <p>
                <b>Performance:</b> {m.performance}%
              </p>
              <p>
                <b>Quality:</b> {m.quality}%
              </p>
              <p>
                <b>Downtime:</b> {m.downtime_display} hr
              </p>
              <p className="click-hint">
                Click to view downtime history
              </p>
            </div>
          );
        })}
      </div>
      {selectedMachine && (
        <div className="modal-overlay" onClick={closeHistory}>
          <div className="modal-box" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>{selectedMachine} Downtime History</h2>
              <button className="close-button" onClick={closeHistory}>
                X
              </button>
            </div>
            {historyLoading ? (
              <h3>Loading history...</h3>
            ) : historyData.length === 0 ? (
              <p>No downtime history found.</p>
            ) : (
              <div className="table-wrapper">
                <table className="history-table">
                  <thead>
                    <tr>
                      <th>Timestamp</th>
                      <th>EN</th>
                      <th>Machine</th>
                      <th>Shift</th>
                      <th>End Downtime</th>
                      <th>Type Downtime</th>
                      <th>Total Downtime</th>
                      <th>Remark</th>
                    </tr>
                  </thead>
                  <tbody>
                    {historyData.map((row, index) => (
                      <tr key={index}>
                        <td>{row.timestamp}</td>
                        <td>{row.en}</td>
                        <td>{row.machine}</td>
                        <td>{row.shift}</td>
                        <td>{row.end_downtime}</td>
                        <td>{row.type_downtime}</td>
                        <td>
                          <b>{row.total_downtime_display} hr</b>
                          <br />
                          {/* <small>{row.total_downtime}</small> */}
                        </td>
                        <td>{row.remark}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
export default App;