(function () {
  "use strict";

  const lastUpdatedEl = document.getElementById("lastUpdated");
  const staleWarningEl = document.getElementById("staleWarning");
  const btnRefresh = document.getElementById("btnRefresh");
  const toastEl = document.getElementById("toast");
  const TOAST_DURATION_MS = 4000;

  function escapeHtml(s) {
    if (s == null) return "";
    var div = document.createElement("div");
    div.textContent = String(s);
    return div.innerHTML;
  }

  function ensureCraigslistListingUrl(url) {
    if (url == null || typeof url !== "string") return "#";
    var u = url.trim();
    if (!u) return "#";
    if (u.indexOf("http://") === 0 || u.indexOf("https://") === 0) return u;
    if (u.indexOf("mailto:") === 0) return u;
    if (u.indexOf("/") === 0) return "https://sfbay.craigslist.org" + u;
    return "https://sfbay.craigslist.org/" + u;
  }

  function listingUrl(apt) {
    return (apt && apt.source === "portal" && apt.url) ? apt.url : ensureCraigslistListingUrl(apt && apt.url);
  }

  function setLoading(widgetId, msg) {
    var wrap = document.getElementById("widget-" + widgetId);
    if (!wrap) return;
    wrap.innerHTML = '<div class="widget-loading" data-widget="' + escapeHtml(widgetId) + '">' + (msg || "Loading…") + "</div>";
  }

  function setError(widgetId, msg) {
    var wrap = document.getElementById("widget-" + widgetId);
    if (!wrap) return;
    wrap.innerHTML = '<div class="widget-error">' + escapeHtml(msg || "Failed to load") + "</div>";
  }

  function formatVol(v) {
    if (v == null || v === undefined) return "—";
    if (v >= 1e9) return (v / 1e9).toFixed(2) + "B";
    if (v >= 1e6) return (v / 1e6).toFixed(2) + "M";
    if (v >= 1e3) return (v / 1e3).toFixed(2) + "K";
    return String(v);
  }

  function pctClass(pct) {
    if (pct == null) return "num-neutral";
    return pct >= 0 ? "num-up" : "num-down";
  }

  function pctStr(pct) {
    if (pct == null) return "—";
    var sign = pct >= 0 ? "+" : "";
    return sign + (typeof pct === "number" ? pct.toFixed(2) : pct) + "%";
  }

  function formatUpdated(ts) {
    if (!ts) return "Last refreshed: never";
    var d = new Date(ts * 1000);
    var now = Date.now();
    var sec = Math.round((now - d) / 1000);
    if (sec < 60) return "Last refreshed: just now";
    if (sec < 120) return "Last refreshed: 1 min ago";
    if (sec < 3600) return "Last refreshed: " + Math.floor(sec / 60) + " mins ago";
    return "Last refreshed: " + d.toLocaleTimeString();
  }

  function showToast(message, isError) {
    if (!toastEl) return;
    toastEl.textContent = message;
    toastEl.classList.add("toast--visible");
    toastEl.classList.toggle("toast--error", !!isError);
    clearTimeout(toastEl._toastTimer);
    toastEl._toastTimer = setTimeout(function () {
      toastEl.classList.remove("toast--visible", "toast--error");
    }, TOAST_DURATION_MS);
  }

  function setRefreshButtonLoading(loading) {
    if (!btnRefresh) return;
    btnRefresh.disabled = loading;
    btnRefresh.classList.toggle("is-loading", loading);
    var icon = btnRefresh.querySelector(".btn-refresh-icon");
    var text = btnRefresh.querySelector(".btn-refresh-text");
    var spinner = btnRefresh.querySelector(".btn-refresh-spinner");
    if (icon) icon.style.display = loading ? "none" : "";
    if (text) text.textContent = loading ? "Refreshing…" : "Refresh Data";
    if (spinner) spinner.style.display = loading ? "inline-block" : "none";
  }

  function renderStockCard(opts) {
    var ticker = opts.ticker || "";
    var name = opts.name || ticker;
    var price = opts.price;
    var changePct = opts.change_pct;
    var volume = opts.volume;
    var analysis = opts.analysis || "—";
    var competitors = opts.competitor_summary || "";
    var majorMove = opts.major_move;

    var cardClass = "stock-card" +
      (majorMove && changePct != null && changePct > 5 ? " major-gain" : "") +
      (majorMove && changePct != null && changePct < -5 ? " major-loss" : "");

    var dataHtml =
      "<span class=\"stock-card__ticker\">" + escapeHtml(ticker) + "</span>" +
      "<span class=\"stock-card__name\" title=\"" + escapeHtml(name) + "\">" + escapeHtml(name) + "</span>";
    if (price != null) dataHtml += "<span class=\"stock-card__price\">$" + Number(price).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + "</span>";
    dataHtml += "<span class=\"stock-card__pct " + pctClass(changePct) + "\">" + pctStr(changePct) + "</span>";
    if (volume != null) dataHtml += "<span class=\"stock-card__volume\">Vol " + formatVol(volume) + "</span>";

    var bottomHtml = "<div class=\"stock-card__analysis\">" + escapeHtml(analysis).replace(/\n/g, "<br>") + "</div>";
    bottomHtml += "<div class=\"stock-card__competitors\"><strong>vs Competitors:</strong> ";
    if (competitors === "No public competitors available" || competitors === "No public competitors tracked" || !competitors) {
      bottomHtml += "<em>No public competitors tracked</em>";
    } else {
      bottomHtml += escapeHtml(competitors);
    }
    bottomHtml += "</div>";
    bottomHtml += "<div class=\"stock-card__time\">" + formatUpdated(opts.updated_ts || 0) + "</div>";

    return "<div class=\"" + cardClass + "\">" +
      "<div class=\"stock-card__data\">" + dataHtml + "</div>" +
      bottomHtml +
      "</div>";
  }

  function renderPerformanceSummary(data, updatedTs) {
    var wrap = document.getElementById("widget-summary");
    if (!wrap) return;
    if (!data || data.count === 0) {
      wrap.innerHTML = "<div class=\"widget-placeholder\">No data yet. Click Refresh Data.</div>";
      return;
    }
    var avg = data.avg_change_pct;
    var best = data.best;
    var worst = data.worst;
    var html = "<div class=\"summary-stats\">";
    html += "<p class=\"summary-avg\">Portfolio avg: <span class=\"" + pctClass(avg) + "\">" + pctStr(avg) + "</span> (" + data.count + " companies)</p>";
    if (best) html += "<p>Best: <strong>" + escapeHtml(best.ticker) + "</strong> " + escapeHtml(best.name) + " <span class=\"" + pctClass(best.change_pct) + "\">" + pctStr(best.change_pct) + "</span></p>";
    if (worst) html += "<p>Worst: <strong>" + escapeHtml(worst.ticker) + "</strong> " + escapeHtml(worst.name) + " <span class=\"" + pctClass(worst.change_pct) + "\">" + pctStr(worst.change_pct) + "</span></p>";
    html += "</div>";
    wrap.innerHTML = html;
  }

  function renderTopMovers(data, updatedTs) {
    var wrap = document.getElementById("widget-movers");
    if (!wrap) return;
    if (!data || (!data.gainers || data.gainers.length === 0) && (!data.losers || data.losers.length === 0)) {
      wrap.innerHTML = "<div class=\"widget-placeholder\">No data yet. Click Refresh Data.</div>";
      return;
    }
    var html = "<div class=\"movers-two-col\">";
    html += "<div><div class=\"movers-section-title\">Top gainers</div><ul class=\"movers-list\">";
    (data.gainers || []).forEach(function (r) {
      html += "<li><span class=\"ticker\">" + escapeHtml(r.ticker) + "</span> " + escapeHtml(r.name) + " <span class=\"" + pctClass(r.change_pct) + "\">" + pctStr(r.change_pct) + "</span></li>";
    });
    html += "</ul></div><div><div class=\"movers-section-title\">Top losers</div><ul class=\"movers-list\">";
    (data.losers || []).forEach(function (r) {
      html += "<li><span class=\"ticker\">" + escapeHtml(r.ticker) + "</span> " + escapeHtml(r.name) + " <span class=\"" + pctClass(r.change_pct) + "\">" + pctStr(r.change_pct) + "</span></li>";
    });
    html += "</ul></div></div>";
    wrap.innerHTML = html;
  }

  function renderPortfolioVsMarket(data, updatedTs) {
    var wrap = document.getElementById("widget-vs-market");
    if (!wrap) return;
    if (!data || data.portfolio_avg_pct == null && data.spy_pct == null) {
      wrap.innerHTML = "<div class=\"widget-placeholder\">No data yet. Click Refresh Data.</div>";
      return;
    }
    var html = "<div class=\"vs-market-stats\">";
    if (data.portfolio_avg_pct != null) html += "<p>Portfolio avg: <span class=\"" + pctClass(data.portfolio_avg_pct) + "\">" + pctStr(data.portfolio_avg_pct) + "</span></p>";
    if (data.spy_pct != null) html += "<p>SPY: <span class=\"" + pctClass(data.spy_pct) + "\">" + pctStr(data.spy_pct) + "</span></p>";
    if (data.outperformance != null) html += "<p>Outperformance: <span class=\"" + pctClass(data.outperformance) + "\">" + pctStr(data.outperformance) + "</span></p>";
    html += "</div>";
    wrap.innerHTML = html;
  }

  function renderTrending(data, fallbackUsed) {
    var wrap = document.getElementById("widget-trending");
    if (!wrap) return;
    var msg = fallbackUsed ? "<p class=\"widget-fallback-msg\">Using fallback data — Yahoo screeners unavailable</p>" : "";
    if (!Array.isArray(data) || data.length === 0) {
      wrap.innerHTML = "<div class=\"widget-placeholder\">No data yet. Click Refresh Data.</div>";
      return;
    }
    var html = msg + "<ul class=\"movers-list movers-list--with-analysis\">";
    data.forEach(function (r) {
      html += "<li><span class=\"ticker\">" + escapeHtml(r.ticker) + "</span> " + escapeHtml(r.name || r.ticker) + " <span class=\"" + pctClass(r.change_pct) + "\">" + pctStr(r.change_pct) + "</span>" + (r.volume != null ? " <span class=\"vol\">Vol " + formatVol(r.volume) + "</span>" : "") + "";
      if (r.analysis) html += "<p class=\"widget-stock-analysis\">" + escapeHtml(r.analysis) + "</p>";
      html += "</li>";
    });
    html += "</ul>";
    wrap.innerHTML = html;
  }

  function renderGainers(data, fallbackUsed) {
    var wrap = document.getElementById("widget-gainers");
    if (!wrap) return;
    var msg = fallbackUsed ? "<p class=\"widget-fallback-msg\">Using fallback data — Yahoo screeners unavailable</p>" : "";
    if (!Array.isArray(data) || data.length === 0) {
      wrap.innerHTML = "<div class=\"widget-placeholder\">No data yet. Click Refresh Data.</div>";
      return;
    }
    var html = msg + "<ul class=\"movers-list movers-list--with-analysis\">";
    data.forEach(function (r) {
      html += "<li><span class=\"ticker\">" + escapeHtml(r.ticker) + "</span> " + escapeHtml(r.name || r.ticker) + " <span class=\"" + pctClass(r.change_pct) + "\">" + pctStr(r.change_pct) + "</span>";
      if (r.analysis) html += "<p class=\"widget-stock-analysis\">" + escapeHtml(r.analysis) + "</p>";
      html += "</li>";
    });
    html += "</ul>";
    wrap.innerHTML = html;
  }

  function renderLosers(data, fallbackUsed) {
    var wrap = document.getElementById("widget-losers");
    if (!wrap) return;
    var msg = fallbackUsed ? "<p class=\"widget-fallback-msg\">Using fallback data — Yahoo screeners unavailable</p>" : "";
    if (!Array.isArray(data) || data.length === 0) {
      wrap.innerHTML = "<div class=\"widget-placeholder\">No data yet. Click Refresh Data.</div>";
      return;
    }
    var html = msg + "<ul class=\"movers-list movers-list--with-analysis\">";
    data.forEach(function (r) {
      html += "<li><span class=\"ticker\">" + escapeHtml(r.ticker) + "</span> " + escapeHtml(r.name || r.ticker) + " <span class=\"" + pctClass(r.change_pct) + "\">" + pctStr(r.change_pct) + "</span>";
      if (r.analysis) html += "<p class=\"widget-stock-analysis\">" + escapeHtml(r.analysis) + "</p>";
      html += "</li>";
    });
    html += "</ul>";
    wrap.innerHTML = html;
  }

  function countdownTo(releaseTs) {
    if (!releaseTs) return { text: "—", urgency: "none" };
    var now = Math.floor(Date.now() / 1000);
    var sec = releaseTs - now;
    if (sec <= 0) return { text: "Released", urgency: "past" };
    var d = Math.floor(sec / 86400);
    var h = Math.floor((sec % 86400) / 3600);
    var m = Math.floor((sec % 3600) / 60);
    var text;
    if (d >= 7) text = "In " + d + " days";
    else if (d >= 1) text = "In " + d + "d " + h + "h";
    else if (h >= 1) text = "In " + h + "h " + m + "m";
    else if (m >= 1) text = "In " + m + " min";
    else text = "In " + sec + " sec";
    var urgency = d >= 7 ? "far" : (d >= 1 ? "soon" : (h >= 1 ? "today" : "imminent"));
    return { text: text, urgency: urgency };
  }

  function updateEconomicCalendar(data) {
    if (!data || !data.economic_calendar) return;

    var cal = data.economic_calendar;
    var iconMap = {
      "Jobs Report": "\uD83D\uDCBC",
      "Non-Farm Payrolls": "\uD83D\uDCBC",
      "CPI": "\uD83D\uDCCA",
      "CPI Release": "\uD83D\uDCCA",
      "Consumer Price Index": "\uD83D\uDCCA",
      "Core CPI": "\uD83D\uDCCA",
      "GDP": "\uD83D\uDCC8",
      "GDP Growth": "\uD83D\uDCC8",
      "FOMC": "\uD83C\uDFDB\uFE0F",
      "FOMC Rate Decision": "\uD83C\uDFDB\uFE0F",
      "Unemployment Rate": "\uD83D\uDCBC"
    };

    var recentDiv = document.getElementById("recentEconCards");
    if (recentDiv) {
      recentDiv.innerHTML = "";
      if (cal.recent_releases && cal.recent_releases.length > 0) {
        cal.recent_releases.forEach(function (release) {
          var icon = iconMap[release.name] || "\uD83D\uDCCB";
          var isPositive = release.change_direction === "up";
          var badge = release.beat_forecast ? "BEAT" : (release.miss_forecast ? "MISS" : "");
          var card = document.createElement("div");
          card.className = "econ-card recent";
          card.innerHTML =
            "<div class=\"event-icon\">" + icon + "</div>" +
            "<div class=\"event-name\">" + escapeHtml(release.name || "") + "</div>" +
            "<div class=\"event-date\">" + escapeHtml(release.date || "") + "</div>" +
            "<div class=\"result\">" +
            "<span class=\"actual " + (isPositive ? "positive" : "negative") + "\">" + escapeHtml(release.actual || "") + " " + (isPositive ? "\u2191" : "\u2193") + "</span>" +
            "<span class=\"vs-label\">vs</span>" +
            "<span class=\"previous\">" + escapeHtml(release.previous || "") + "</span>" +
            "</div>" +
            (badge ? "<div class=\"" + badge.toLowerCase() + "-badge\">" + escapeHtml(badge) + "</div>" : "");
          recentDiv.appendChild(card);
        });
      } else {
        recentDiv.innerHTML = "<div class=\"no-data\">No recent releases</div>";
      }
    }

    var upcomingDiv = document.getElementById("upcomingEconCards");
    if (upcomingDiv) {
      upcomingDiv.innerHTML = "";
      if (cal.upcoming_releases && cal.upcoming_releases.length > 0) {
        cal.upcoming_releases.forEach(function (event) {
          var icon = iconMap[event.name] || "\uD83D\uDCCB";
          var card = document.createElement("div");
          card.className = "econ-card upcoming";
          card.innerHTML =
            "<div class=\"event-icon\">" + icon + "</div>" +
            "<div class=\"event-name\">" + escapeHtml(event.name || "") + "</div>" +
            "<div class=\"event-datetime\">" +
            "<div class=\"date\">" + escapeHtml(event.date || "") + "</div>" +
            "<div class=\"time\">" + escapeHtml(event.time || "") + "</div>" +
            "</div>" +
            "<div class=\"countdown urgency-" + escapeHtml(event.urgency || "low") + "\">" + escapeHtml(event.countdown_text || "") + "</div>" +
            "<div class=\"forecast-data\">" + escapeHtml(event.forecast_summary || event.forecast || "") + "</div>";
          upcomingDiv.appendChild(card);
        });
      } else {
        upcomingDiv.innerHTML = "<div class=\"no-data\">No upcoming events</div>";
      }
    }
  }

  function renderPortfolio(data, updatedTs) {
    var wrap = document.getElementById("widget-portfolio");
    if (!wrap) return;
    if (!Array.isArray(data) || data.length === 0) {
      wrap.innerHTML = "<div class=\"widget-placeholder\">No data yet. Click Refresh Data to load.</div>";
      return;
    }
    var html = "<div class=\"stock-list\">";
    data.forEach(function (r) {
      html += renderStockCard({
        ticker: r.ticker,
        name: r.name,
        price: r.price,
        change_pct: r.change_pct,
        volume: r.volume,
        analysis: r.analysis,
        competitor_summary: r.competitor_summary,
        major_move: r.major_move,
        updated_ts: updatedTs,
      });
    });
    html += "</div>";
    wrap.innerHTML = html;
  }

  function applyDashboard(payload) {
    var updated = payload.updated || 0;
    var mf = payload.market_fallback || {};
    renderPerformanceSummary(payload.performance_summary || {}, updated);
    renderTopMovers(payload.top_movers || {}, updated);
    renderPortfolioVsMarket(payload.portfolio_vs_market || {}, updated);
    renderTrending(payload.trending || [], mf.trending);
    renderGainers(payload.gainers || [], mf.gainers);
    renderLosers(payload.losers || [], mf.losers);
    updateEconomicCalendar(payload);
    renderPortfolio(payload.portfolio || [], updated);
    if (lastUpdatedEl) lastUpdatedEl.textContent = formatUpdated(updated);
    if (staleWarningEl) {
      var age = Date.now() / 1000 - updated;
      staleWarningEl.classList.toggle("hidden", age < 600);
    }
  }

  function loadDashboard(showLoadingSpinners) {
    if (showLoadingSpinners) {
      setLoading("summary");
      setLoading("movers");
      setLoading("vs-market");
      setLoading("trending");
      setLoading("gainers");
      setLoading("losers");
      setLoading("portfolio");
    }

    fetch("/api/dashboard")
      .then(function (r) { return r.json(); })
      .then(function (payload) {
        applyDashboard(payload);
      })
      .catch(function (err) {
        if (showLoadingSpinners) {
          setError("summary", err.message);
          setError("movers", err.message);
          setError("vs-market", err.message);
          setError("trending", err.message);
          setError("gainers", err.message);
          setError("losers", err.message);
          setError("portfolio", err.message);
        }
        if (lastUpdatedEl) lastUpdatedEl.textContent = "Last refreshed: never";
      });
  }

  if (btnRefresh) {
    btnRefresh.addEventListener("click", function () {
      if (btnRefresh.disabled) return;
      setRefreshButtonLoading(true);
      var startTime = Date.now();

      fetch("/api/refresh", { method: "POST" })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          loadDashboard(true);
          var durationSec = (Date.now() - startTime) / 1000;
          var msg = "Data refreshed successfully. Refreshed in " + Math.round(durationSec) + " seconds.";
          if (data.succeeded != null && data.failed != null && data.failed > 0) {
            msg += " " + data.succeeded + " succeeded, " + data.failed + " failed.";
          }
          showToast(msg, false);
        })
        .catch(function (err) {
          showToast("Refresh failed: " + (err.message || "Network error"), true);
          loadDashboard(false);
        })
        .finally(function () {
          setRefreshButtonLoading(false);
        });
    });
  }

  loadDashboard(true);

  function injectAdSenseOnce() {
    if (window.adsenseInjected) return;
    window.adsenseInjected = true;
    var s = document.createElement("script");
    s.async = true;
    s.src = "https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-8564212603961775";
    s.crossOrigin = "anonymous";
    document.head.appendChild(s);
  }

  function setDashboardTheme(tabName) {
    var t = tabName || "markets";
    if (t === "apartments-alt") t = "apartments";
    if (t === "stanford-apartments-alt") t = "stanford-apartments";
    document.body.setAttribute("data-theme", t);
  }
  var activeTabBtn = document.querySelector(".tab-btn.active");
  var initialTab = activeTabBtn ? activeTabBtn.getAttribute("data-tab") : "apartments";
  setDashboardTheme(initialTab);
  if (initialTab === "apartments" || initialTab === "stanford-apartments") injectAdSenseOnce();
  if (initialTab === "apartments" && !window.apartmentsLoaded) {
    loadApartments();
    window.apartmentsLoaded = true;
  }
  if (initialTab === "stanford-apartments" && !window.stanfordApartmentsLoaded) {
    loadStanfordApartments();
    window.stanfordApartmentsLoaded = true;
  }
  if (initialTab === "apartments-alt" && !window.apartmentsAltLoaded) {
    loadApartmentsAlt();
    window.apartmentsAltLoaded = true;
  }
  if (initialTab === "stanford-apartments-alt" && !window.stanfordApartmentsAltLoaded) {
    loadStanfordApartmentsAlt();
    window.stanfordApartmentsAltLoaded = true;
  }

  document.querySelectorAll(".tab-btn").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var tabName = btn.getAttribute("data-tab");
      document.querySelectorAll(".tab-btn").forEach(function (b) { b.classList.remove("active"); b.setAttribute("aria-selected", "false"); });
      document.querySelectorAll(".tab-content").forEach(function (c) { c.classList.remove("active"); });
      btn.classList.add("active");
      btn.setAttribute("aria-selected", "true");
      setDashboardTheme(tabName);
      var content = document.getElementById(tabName + "-tab");
      if (content) content.classList.add("active");
      if (tabName === "apartments" || tabName === "stanford-apartments") injectAdSenseOnce();
      if (tabName === "apartments" && !window.apartmentsLoaded) {
        loadApartments();
        window.apartmentsLoaded = true;
      }
      if (tabName === "stanford-apartments" && !window.stanfordApartmentsLoaded) {
        loadStanfordApartments();
        window.stanfordApartmentsLoaded = true;
      }
      if (tabName === "apartments-alt" && !window.apartmentsAltLoaded) {
        loadApartmentsAlt();
        window.apartmentsAltLoaded = true;
      }
      if (tabName === "stanford-apartments-alt" && !window.stanfordApartmentsAltLoaded) {
        loadStanfordApartmentsAlt();
        window.stanfordApartmentsAltLoaded = true;
      }
    });
  });

  // --- SF Apartments ---
  var apartmentsData = [];

  function loadApartments() {
    var btn = document.getElementById("refreshApartments");
    if (!btn) return;
    btn.disabled = true;
    btn.textContent = "\uD83D\uDD04 Loading…";
    fetch("/api/apartments/portal")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.error) throw new Error(data.error);
        apartmentsData = data.apartments || [];
        renderApartments(apartmentsData);
        updateApartmentStats(data.stats || {});
        btn.textContent = "\uD83D\uDD04 Refresh Listings";
        btn.disabled = false;
      })
      .catch(function (err) {
        console.error("Error loading apartments:", err);
        var list = document.getElementById("apartmentsList");
        if (list) list.innerHTML = "<div class=\"error-message\">Error loading apartments. Please try again.</div>";
        btn.textContent = "\uD83D\uDD04 Try Again";
        btn.disabled = false;
      });
  }

  function updateApartmentStats(stats) {
    var totalEl = document.getElementById("totalListings");
    var excellentEl = document.getElementById("excellentDeals");
    var avgEl = document.getElementById("avgPrice");
    if (totalEl) totalEl.textContent = stats.total || 0;
    if (excellentEl) excellentEl.textContent = stats.excellent_deals || 0;
    if (avgEl) avgEl.textContent = stats.average_price ? "$" + Number(stats.average_price).toLocaleString() : "$0";
  }

  function neighborhoodSlug(name) {
    if (!name) return "";
    return name.toLowerCase().replace(/\s+/g, "-").replace(/[^a-z0-9-]/g, "");
  }

  function getFilteredAndSortedApartments() {
    var hoodFilter = document.getElementById("neighborhoodFilter");
    var bedFilter = document.getElementById("bedroomFilter");
    var sortBy = document.getElementById("sortBy");
    var list = apartmentsData.slice();
    var hoodVal = hoodFilter ? hoodFilter.value : "all";
    var bedVal = bedFilter ? bedFilter.value : "all";
    var sortVal = sortBy ? sortBy.value : "best-deal";

    if (hoodVal !== "all") {
      list = list.filter(function (apt) {
        var slug = neighborhoodSlug(apt.neighborhood);
        if (hoodVal === "pac-heights") return slug === "pacific-heights" || slug === "pac-heights";
        return slug === hoodVal || slug.indexOf(hoodVal) !== -1;
      });
    }
    if (bedVal !== "all") {
      list = list.filter(function (apt) {
        var b = apt.bedrooms;
        if (bedVal === "studio") return b === 0;
        if (bedVal === "3") return b >= 3;
        return b === parseInt(bedVal, 10);
      });
    }
    if (sortVal === "best-deal") list.sort(function (a, b) { return (b.deal_score || 0) - (a.deal_score || 0); });
    else if (sortVal === "price-low") list.sort(function (a, b) { return (a.price || 0) - (b.price || 0); });
    else if (sortVal === "price-sqft") list.sort(function (a, b) { return (a.price_per_sqft || 999) - (b.price_per_sqft || 999); });
    else if (sortVal === "newest") list.sort(function (a, b) { return (b.posted_date || "").localeCompare(a.posted_date || ""); });
    return list;
  }

  function renderApartments(apartments) {
    var container = document.getElementById("apartmentsList");
    if (!container) return;
    if (apartments && apartments.length) apartmentsData = apartments;
    var list = getFilteredAndSortedApartments();
    container.innerHTML = "";

    if (!list.length) {
      container.innerHTML = "<div class=\"no-apartments\">No apartments found in the $2,000–$5,000 range. Try refreshing or adjust filters.</div>";
      return;
    }

    list.forEach(function (apt) {
      var card = document.createElement("div");
      card.className = "apartment-card";
      var badgeClass = "deal-badge";
      if (apt.deal_score >= 80) badgeClass += " excellent";
      else if (apt.deal_score >= 65) badgeClass += " good";
      else if (apt.deal_score >= 50) badgeClass += " fair";
      else badgeClass += " poor";
      var bedStr = apt.bedrooms === 0 ? "Studio" : apt.bedrooms + " bed";
      var bathStr = apt.bathrooms != null ? apt.bathrooms + " bath" : "";
      var sqftStr = apt.sqft ? apt.sqft + " sqft" : "";
      var marketHtml = "";
      if (apt.discount_pct != null && apt.discount_pct !== undefined) {
        var pct = apt.discount_pct;
        var marketLabel = pct > 0 ? Math.abs(pct).toFixed(0) + "% below market" : (pct < 0 ? Math.abs(pct).toFixed(0) + "% above market" : "At market");
        var marketCls = pct > 0 ? "positive" : (pct < 0 ? "negative" : "neutral");
        marketHtml = "<div class=\"metric\"><span class=\"metric-label\">vs Market</span><span class=\"metric-value " + marketCls + "\">" + marketLabel + "</span></div>";
      }
      var neighborhoodForMap = (apt.neighborhood || "San Francisco").trim();
      var lat = apt.latitude != null && apt.longitude != null ? Number(apt.latitude) : null;
      var lon = apt.latitude != null && apt.longitude != null ? Number(apt.longitude) : null;
      var defaultSF = [37.7849, -122.4094];
      if (lat === null || lon === null) {
        var sfNeighborhoods = { "mission": [37.7599, -122.4148], "soma": [37.7786, -122.4056], "south beach": [37.7786, -122.4056], "nob hill": [37.7928, -122.4155], "nob-hill": [37.7928, -122.4155], "marina": [37.8025, -122.4364], "sunset": [37.7540, -122.5042], "richmond": [37.7804, -122.4602], "seacliff": [37.7844, -122.4922], "castro": [37.7609, -122.4350], "haight": [37.7699, -122.4464], "haight-ashbury": [37.7699, -122.4464], "pacific heights": [37.7912, -122.4368], "pac heights": [37.7912, -122.4368], "inner sunset": [37.7543, -122.4650], "downtown": [37.7849, -122.4094], "financial district": [37.7940, -122.3998], "noe valley": [37.7512, -122.4337], "mission district": [37.7599, -122.4148], "tenderloin": [37.7844, -122.4092], "nopa": [37.7769, -122.4384], "alamo square": [37.7765, -122.4322], "russian hill": [37.8010, -122.4205], "north beach": [37.8050, -122.4102], "potrero hill": [37.7582, -122.4040], "hayes valley": [37.7766, -122.4224], "lower nob hill": [37.7882, -122.4128], "twin peaks": [37.7544, -122.4474], "ingleside": [37.7242, -122.4522], "bayview": [37.7300, -122.3870], "excelsior": [37.7228, -122.4333], "outer mission": [37.7228, -122.4333], "san francisco": [37.7849, -122.4094], "sf": [37.7849, -122.4094], "laurel hts": [37.7870, -122.4530], "presidio": [37.8000, -122.4660], "daly city": [37.7059, -122.4709] };
        var key = neighborhoodForMap.toLowerCase().replace(/\s+/g, " ").trim().replace(/\s/g, "-");
        var coords = sfNeighborhoods[key] || sfNeighborhoods[key.replace(/-/g, " ")];
        if (!coords && key.indexOf("/") !== -1) {
          var parts = key.split("/").map(function (p) { return p.replace(/-/g, " ").trim(); });
          for (var i = 0; i < parts.length && !coords; i++) { coords = sfNeighborhoods[parts[i]] || sfNeighborhoods[parts[i].replace(/\s/g, "-")]; }
        }
        if (coords) { lat = coords[0]; lon = coords[1]; } else { lat = defaultSF[0]; lon = defaultSF[1]; }
      }
      var photoBox = "";
      var viewUrl = listingUrl(apt);
      if (apt.thumbnail_url) {
        photoBox = "<div class=\"apt-photo-wrap\"><a href=\"" + escapeHtml(viewUrl) + "\" target=\"_blank\" rel=\"noopener noreferrer\" class=\"apt-thumbnail-link\"><img class=\"apt-thumbnail\" src=\"" + escapeHtml(apt.thumbnail_url) + "\" alt=\"Listing\" loading=\"lazy\" /></a></div>";
      } else if (lat !== null && lon !== null) {
        var bbox = (lon - 0.015).toFixed(4) + "," + (lat - 0.01).toFixed(4) + "," + (lon + 0.015).toFixed(4) + "," + (lat + 0.01).toFixed(4);
        var mapUrl = "https://www.openstreetmap.org/export/embed.html?bbox=" + encodeURIComponent(bbox) + "&layer=mapnik&marker=" + encodeURIComponent(lat + "," + lon);
        photoBox = "<div class=\"apt-map-wrap\"><iframe class=\"apt-map-iframe\" sandbox=\"allow-scripts\" title=\"Map: " + escapeHtml(neighborhoodForMap) + "\" src=\"" + escapeHtml(mapUrl) + "\" loading=\"lazy\"></iframe><div class=\"apt-map-label\">\uD83D\uDCCD " + escapeHtml(neighborhoodForMap) + ", San Francisco</div></div>";
      } else {
        var mapSearchQuery = encodeURIComponent(neighborhoodForMap + ", San Francisco, CA");
        photoBox = "<div class=\"apt-photo-placeholder apt-location-placeholder\"><span class=\"apt-photo-icon\">\uD83D\uDCCD</span><span class=\"apt-photo-text\">" + escapeHtml(neighborhoodForMap) + "</span><span class=\"apt-photo-sub\">San Francisco</span><a href=\"https://www.google.com/maps/search/?api=1&query=" + mapSearchQuery + "\" target=\"_blank\" rel=\"noopener noreferrer\" class=\"apt-map-link\">View on map</a></div>";
      }
      card.innerHTML =
        photoBox +
        "<div class=\"" + badgeClass + "\">" + (apt.deal_score != null ? apt.deal_score : 0) + "/100</div>" +
        "<div class=\"apt-header\">" +
        "<h3 class=\"apt-title\">" + escapeHtml(apt.title || "Apartment Listing") + "</h3>" +
        "<div class=\"apt-price\">$" + (apt.price ? Number(apt.price).toLocaleString() : "0") + "/mo</div>" +
        "</div>" +
        "<div class=\"apt-details\">" +
        "<span class=\"apt-detail\">\uD83D\uCCCD " + escapeHtml(apt.neighborhood || "Unknown") + "</span>" +
        "<span class=\"apt-detail\">\uD83E\uDDE1 " + bedStr + "</span>" +
        (bathStr ? "<span class=\"apt-detail\">\uD83D\uDEBF " + bathStr + "</span>" : "") +
        (sqftStr ? "<span class=\"apt-detail\">\uD83D\uDCCF " + sqftStr + "</span>" : "") +
        (apt.laundry_type === "in_unit" ? "<span class=\"apt-detail\">\uD83D\uDED1 In-unit W/D</span>" : (apt.laundry_type === "in_building" ? "<span class=\"apt-detail\">\uD83D\uDED1 Laundry in bldg</span>" : "")) +
        (apt.parking ? "<span class=\"apt-detail\">\uD83D\uDE8C Parking</span>" : "") +
        "</div>" +
        "<div class=\"apt-metrics\">" +
        (apt.price_per_sqft ? "<div class=\"metric\"><span class=\"metric-label\">Price/Sqft</span><span class=\"metric-value\">$" + Number(apt.price_per_sqft).toFixed(2) + "</span></div>" : "") +
        marketHtml +
        "</div>" +
        "<div class=\"apt-analysis\">\uD83E\uDD16 " + escapeHtml(apt.deal_analysis || "Analysis pending…") + "</div>" +
        "<a href=\"" + escapeHtml(viewUrl) + "\" target=\"_blank\" rel=\"noopener noreferrer\" class=\"apt-link\">View Listing \u2192</a>";
      container.appendChild(card);
    });
  }

  var refreshBtn = document.getElementById("refreshApartments");
  if (refreshBtn) {
    refreshBtn.addEventListener("click", function () {
      refreshBtn.disabled = true;
      refreshBtn.textContent = "\uD83D\uDD04 Refreshing…";
      fetch("/api/apartments/portal")
        .then(function (r) { return r.json(); })
        .then(function (data) {
          apartmentsData = data.apartments || [];
          renderApartments(apartmentsData);
          updateApartmentStats(data.stats || {});
          refreshBtn.textContent = "\uD83D\uDD04 Refresh Listings";
          refreshBtn.disabled = false;
        })
        .catch(function (err) {
          console.error("Refresh error:", err);
          refreshBtn.textContent = "\uD83D\uDD04 Try Again";
          refreshBtn.disabled = false;
        });
    });
  }

  var neighborhoodFilter = document.getElementById("neighborhoodFilter");
  var bedroomFilter = document.getElementById("bedroomFilter");
  var sortBy = document.getElementById("sortBy");
  if (neighborhoodFilter) neighborhoodFilter.addEventListener("change", function () { renderApartments(); });
  if (bedroomFilter) bedroomFilter.addEventListener("change", function () { renderApartments(); });
  if (sortBy) sortBy.addEventListener("change", function () { renderApartments(); });

  // --- Stanford Area Apartments ---
  var stanfordApartmentsData = [];
  var STANFORD_NEIGHBORHOODS = {
    "palo alto": [37.4419, -122.1430], "palo-alto": [37.4419, -122.1430],
    "menlo park": [37.4538, -122.1822], "menlo-park": [37.4538, -122.1822],
    "redwood city": [37.4852, -122.2364], "redwood-city": [37.4852, -122.2364], "redwood shores": [37.5311, -122.2486],
    "mountain view": [37.3861, -122.0839], "mountain-view": [37.3861, -122.0839],
    "stanford": [37.4275, -122.1697],
    "east palo alto": [37.4688, -122.1411], "east-palo-alto": [37.4688, -122.1411],
    "downtown": [37.4419, -122.1430], "downtown palo alto": [37.4419, -122.1430], "downtown menlo park": [37.4538, -122.1822],
    "old palo alto": [37.4480, -122.1420], "college terrace": [37.4180, -122.1380], "crescent park": [37.4580, -122.1350],
    "los altos": [37.3852, -122.1141], "los-altos": [37.3852, -122.1141], "woodside": [37.4292, -122.2542], "atherton": [37.4613, -122.1977]
  };
  function stanfordCoordsFromNeighborhood(neighborhoodForMap) {
    var key = (neighborhoodForMap || "palo alto").toString().toLowerCase().replace(/\s+/g, " ").trim().replace(/\s/g, "-");
    var coords = STANFORD_NEIGHBORHOODS[key] || STANFORD_NEIGHBORHOODS[key.replace(/-/g, " ")];
    if (!coords && key.indexOf("/") !== -1) {
      var parts = key.split("/").map(function (p) { return p.replace(/-/g, " ").trim(); });
      for (var i = 0; i < parts.length && !coords; i++) { coords = STANFORD_NEIGHBORHOODS[parts[i]] || STANFORD_NEIGHBORHOODS[parts[i].replace(/\s/g, "-")]; }
    }
    if (!coords) {
      var lower = key.replace(/-/g, " ");
      if (lower.indexOf("palo alto") !== -1 || lower.indexOf("palo-alto") !== -1) coords = [37.4419, -122.1430];
      else if (lower.indexOf("menlo") !== -1) coords = [37.4538, -122.1822];
      else if (lower.indexOf("redwood") !== -1) coords = [37.4852, -122.2364];
      else if (lower.indexOf("mountain view") !== -1 || lower.indexOf("mountain-view") !== -1) coords = [37.3861, -122.0839];
      else if (lower.indexOf("stanford") !== -1) coords = [37.4275, -122.1697];
      else if (lower.indexOf("east palo") !== -1) coords = [37.4688, -122.1411];
      else if (lower.indexOf("los altos") !== -1) coords = [37.3852, -122.1141];
      else if (lower.indexOf("woodside") !== -1 || lower.indexOf("atherton") !== -1) coords = [37.4292, -122.2542];
    }
    return coords || [37.4419, -122.1430];
  }
  var STANFORD_DEFAULT = [37.4419, -122.1430];

  function loadStanfordApartments() {
    var btn = document.getElementById("refreshStanfordApartments");
    if (!btn) return;
    btn.disabled = true;
    btn.textContent = "\uD83D\uDD04 Loading…";
    fetch("/api/apartments/portal/stanford")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.error) throw new Error(data.error);
        stanfordApartmentsData = data.apartments || [];
        renderStanfordApartments(stanfordApartmentsData);
        updateStanfordApartmentStats(data.stats || {});
        btn.textContent = "\uD83D\uDD04 Refresh Listings";
        btn.disabled = false;
      })
      .catch(function (err) {
        console.error("Error loading Stanford apartments:", err);
        var list = document.getElementById("stanfordApartmentsList");
        if (list) list.innerHTML = "<div class=\"error-message\">Error loading listings. Please try again.</div>";
        btn.textContent = "\uD83D\uDD04 Try Again";
        btn.disabled = false;
      });
  }

  function updateStanfordApartmentStats(stats) {
    var totalEl = document.getElementById("stanfordTotalListings");
    var excellentEl = document.getElementById("stanfordExcellentDeals");
    var avgEl = document.getElementById("stanfordAvgPrice");
    if (totalEl) totalEl.textContent = stats.total || 0;
    if (excellentEl) excellentEl.textContent = stats.excellent_deals || 0;
    if (avgEl) avgEl.textContent = stats.average_price ? "$" + Number(stats.average_price).toLocaleString() : "$0";
  }

  function getFilteredAndSortedStanfordApartments() {
    var hoodFilter = document.getElementById("stanfordNeighborhoodFilter");
    var bedFilter = document.getElementById("stanfordBedroomFilter");
    var sortBy = document.getElementById("stanfordSortBy");
    var list = stanfordApartmentsData.slice();
    var hoodVal = hoodFilter ? hoodFilter.value : "all";
    var bedVal = bedFilter ? bedFilter.value : "all";
    var sortVal = sortBy ? sortBy.value : "best-deal";
    if (hoodVal !== "all") {
      list = list.filter(function (apt) {
        var slug = neighborhoodSlug(apt.neighborhood);
        return slug === hoodVal || slug.indexOf(hoodVal) !== -1;
      });
    }
    if (bedVal !== "all") {
      list = list.filter(function (apt) {
        var b = apt.bedrooms;
        if (bedVal === "studio") return b === 0;
        if (bedVal === "3") return b >= 3;
        return b === parseInt(bedVal, 10);
      });
    }
    if (sortVal === "best-deal") list.sort(function (a, b) { return (b.deal_score || 0) - (a.deal_score || 0); });
    else if (sortVal === "price-low") list.sort(function (a, b) { return (a.price || 0) - (b.price || 0); });
    else if (sortVal === "price-sqft") list.sort(function (a, b) { return (a.price_per_sqft || 999) - (b.price_per_sqft || 999); });
    else if (sortVal === "newest") list.sort(function (a, b) { return (b.posted_date || "").localeCompare(a.posted_date || ""); });
    return list;
  }

  function renderStanfordApartments(apartments) {
    var container = document.getElementById("stanfordApartmentsList");
    if (!container) return;
    if (apartments && apartments.length) stanfordApartmentsData = apartments;
    var list = getFilteredAndSortedStanfordApartments();
    container.innerHTML = "";
    if (!list.length) {
      container.innerHTML = "<div class=\"no-apartments\">No apartments in this range. Try refreshing or adjust filters.</div>";
      return;
    }
    list.forEach(function (apt) {
      var card = document.createElement("div");
      card.className = "apartment-card";
      var badgeClass = "deal-badge";
      if (apt.deal_score >= 80) badgeClass += " excellent";
      else if (apt.deal_score >= 65) badgeClass += " good";
      else if (apt.deal_score >= 50) badgeClass += " fair";
      else badgeClass += " poor";
      var bedStr = apt.bedrooms === 0 ? "Studio" : apt.bedrooms + " bed";
      var bathStr = apt.bathrooms != null ? apt.bathrooms + " bath" : "";
      var sqftStr = apt.sqft ? apt.sqft + " sqft" : "";
      var marketHtml = "";
      if (apt.discount_pct != null && apt.discount_pct !== undefined) {
        var pct = apt.discount_pct;
        var marketLabel = pct > 0 ? Math.abs(pct).toFixed(0) + "% below market" : (pct < 0 ? Math.abs(pct).toFixed(0) + "% above market" : "At market");
        var marketCls = pct > 0 ? "positive" : (pct < 0 ? "negative" : "neutral");
        marketHtml = "<div class=\"metric\"><span class=\"metric-label\">vs Market</span><span class=\"metric-value " + marketCls + "\">" + marketLabel + "</span></div>";
      }
      var neighborhoodForMap = (apt.neighborhood || "Palo Alto").trim();
      var lat = apt.latitude != null && apt.longitude != null ? Number(apt.latitude) : null;
      var lon = apt.latitude != null && apt.longitude != null ? Number(apt.longitude) : null;
      if (lat === null || lon === null) {
        var coords = stanfordCoordsFromNeighborhood(neighborhoodForMap);
        lat = coords[0]; lon = coords[1];
      }
      var photoBox = "";
      var viewUrl = listingUrl(apt);
      if (apt.thumbnail_url) {
        photoBox = "<div class=\"apt-photo-wrap\"><a href=\"" + escapeHtml(viewUrl) + "\" target=\"_blank\" rel=\"noopener noreferrer\" class=\"apt-thumbnail-link\"><img class=\"apt-thumbnail\" src=\"" + escapeHtml(apt.thumbnail_url) + "\" alt=\"Listing\" loading=\"lazy\" /></a></div>";
      } else if (lat !== null && lon !== null) {
        var bbox = (lon - 0.015).toFixed(4) + "," + (lat - 0.01).toFixed(4) + "," + (lon + 0.015).toFixed(4) + "," + (lat + 0.01).toFixed(4);
        var mapUrl = "https://www.openstreetmap.org/export/embed.html?bbox=" + encodeURIComponent(bbox) + "&layer=mapnik&marker=" + encodeURIComponent(lat + "," + lon);
        photoBox = "<div class=\"apt-map-wrap\"><iframe class=\"apt-map-iframe\" sandbox=\"allow-scripts\" title=\"Map: " + escapeHtml(neighborhoodForMap) + "\" src=\"" + escapeHtml(mapUrl) + "\" loading=\"lazy\"></iframe><div class=\"apt-map-label\">\uD83D\uDCCD " + escapeHtml(neighborhoodForMap) + ", Stanford area</div></div>";
      } else {
        var mapSearchQuery = encodeURIComponent(neighborhoodForMap + ", CA");
        photoBox = "<div class=\"apt-photo-placeholder apt-location-placeholder\"><span class=\"apt-photo-icon\">\uD83D\uDCCD</span><span class=\"apt-photo-text\">" + escapeHtml(neighborhoodForMap) + "</span><span class=\"apt-photo-sub\">Stanford area</span><a href=\"https://www.google.com/maps/search/?api=1&query=" + mapSearchQuery + "\" target=\"_blank\" rel=\"noopener noreferrer\" class=\"apt-map-link\">View on map</a></div>";
      }
      card.innerHTML =
        photoBox +
        "<div class=\"" + badgeClass + "\">" + (apt.deal_score != null ? apt.deal_score : 0) + "/100</div>" +
        "<div class=\"apt-header\">" +
        "<h3 class=\"apt-title\">" + escapeHtml(apt.title || "Apartment Listing") + "</h3>" +
        "<div class=\"apt-price\">$" + (apt.price ? Number(apt.price).toLocaleString() : "0") + "/mo</div>" +
        "</div>" +
        "<div class=\"apt-details\">" +
        "<span class=\"apt-detail\">\uD83D\uCCCD " + escapeHtml(apt.neighborhood || "Unknown") + "</span>" +
        "<span class=\"apt-detail\">\uD83E\uDDE1 " + bedStr + "</span>" +
        (bathStr ? "<span class=\"apt-detail\">\uD83D\uDEBF " + bathStr + "</span>" : "") +
        (sqftStr ? "<span class=\"apt-detail\">\uD83D\uDCCF " + sqftStr + "</span>" : "") +
        (apt.laundry_type === "in_unit" ? "<span class=\"apt-detail\">\uD83D\uDED1 In-unit W/D</span>" : (apt.laundry_type === "in_building" ? "<span class=\"apt-detail\">\uD83D\uDED1 Laundry in bldg</span>" : "")) +
        (apt.parking ? "<span class=\"apt-detail\">\uD83D\uDE8C Parking</span>" : "") +
        "</div>" +
        "<div class=\"apt-metrics\">" +
        (apt.price_per_sqft ? "<div class=\"metric\"><span class=\"metric-label\">Price/Sqft</span><span class=\"metric-value\">$" + Number(apt.price_per_sqft).toFixed(2) + "</span></div>" : "") +
        marketHtml +
        "</div>" +
        "<div class=\"apt-analysis\">\uD83E\uDD16 " + escapeHtml(apt.deal_analysis || "Analysis pending…") + "</div>" +
        "<a href=\"" + escapeHtml(viewUrl) + "\" target=\"_blank\" rel=\"noopener noreferrer\" class=\"apt-link\">View Listing \u2192</a>";
      container.appendChild(card);
    });
  }

  var refreshStanfordBtn = document.getElementById("refreshStanfordApartments");
  if (refreshStanfordBtn) {
    refreshStanfordBtn.addEventListener("click", function () {
      refreshStanfordBtn.disabled = true;
      refreshStanfordBtn.textContent = "\uD83D\uDD04 Refreshing…";
      fetch("/api/apartments/portal/stanford")
        .then(function (r) { return r.json(); })
        .then(function (data) {
          stanfordApartmentsData = data.apartments || [];
          renderStanfordApartments(stanfordApartmentsData);
          updateStanfordApartmentStats(data.stats || {});
          refreshStanfordBtn.textContent = "\uD83D\uDD04 Refresh Listings";
          refreshStanfordBtn.disabled = false;
        })
        .catch(function (err) {
          console.error("Stanford refresh error:", err);
          refreshStanfordBtn.textContent = "\uD83D\uDD04 Try Again";
          refreshStanfordBtn.disabled = false;
        });
    });
  }
  var stanfordNeighborhoodFilter = document.getElementById("stanfordNeighborhoodFilter");
  var stanfordBedroomFilter = document.getElementById("stanfordBedroomFilter");
  var stanfordSortBy = document.getElementById("stanfordSortBy");
  if (stanfordNeighborhoodFilter) stanfordNeighborhoodFilter.addEventListener("change", function () { renderStanfordApartments(); });
  if (stanfordBedroomFilter) stanfordBedroomFilter.addEventListener("change", function () { renderStanfordApartments(); });
  if (stanfordSortBy) stanfordSortBy.addEventListener("change", function () { renderStanfordApartments(); });

  // --- SF Listings (alternate) ---
  var apartmentsAltData = [];
  function loadApartmentsAlt() {
    var btn = document.getElementById("refreshApartmentsAlt");
    if (!btn) return;
    btn.disabled = true;
    btn.textContent = "\uD83D\uDD04 Loading…";
    fetch("/api/apartments")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.error) throw new Error(data.error);
        apartmentsAltData = data.apartments || [];
        renderApartmentsAlt();
        updateApartmentStatsAlt(data.stats || {});
        btn.textContent = "\uD83D\uDD04 Refresh Listings";
        btn.disabled = false;
      })
      .catch(function (err) {
        console.error("Error loading alternate SF listings:", err);
        var list = document.getElementById("apartmentsListAlt");
        if (list) list.innerHTML = "<div class=\"error-message\">Error loading listings. Please try again.</div>";
        btn.textContent = "\uD83D\uDD04 Try Again";
        btn.disabled = false;
      });
  }
  function updateApartmentStatsAlt(stats) {
    var totalEl = document.getElementById("totalListingsAlt");
    var excellentEl = document.getElementById("excellentDealsAlt");
    var avgEl = document.getElementById("avgPriceAlt");
    if (totalEl) totalEl.textContent = stats.total || 0;
    if (excellentEl) excellentEl.textContent = stats.excellent_deals || 0;
    if (avgEl) avgEl.textContent = stats.average_price ? "$" + Number(stats.average_price).toLocaleString() : "$0";
  }
  function getFilteredAndSortedApartmentsAlt() {
    var hoodFilter = document.getElementById("neighborhoodFilterAlt");
    var bedFilter = document.getElementById("bedroomFilterAlt");
    var sortBy = document.getElementById("sortByAlt");
    var list = apartmentsAltData.slice();
    var hoodVal = hoodFilter ? hoodFilter.value : "all";
    var bedVal = bedFilter ? bedFilter.value : "all";
    var sortVal = sortBy ? sortBy.value : "best-deal";
    if (hoodVal !== "all") {
      list = list.filter(function (apt) {
        var slug = neighborhoodSlug(apt.neighborhood);
        if (hoodVal === "pac-heights") return slug === "pacific-heights" || slug === "pac-heights";
        return slug === hoodVal || slug.indexOf(hoodVal) !== -1;
      });
    }
    if (bedVal !== "all") {
      list = list.filter(function (apt) {
        var b = apt.bedrooms;
        if (bedVal === "studio") return b === 0;
        if (bedVal === "3") return b >= 3;
        return b === parseInt(bedVal, 10);
      });
    }
    if (sortVal === "best-deal") list.sort(function (a, b) { return (b.deal_score || 0) - (a.deal_score || 0); });
    else if (sortVal === "price-low") list.sort(function (a, b) { return (a.price || 0) - (b.price || 0); });
    else if (sortVal === "price-sqft") list.sort(function (a, b) { return (a.price_per_sqft || 999) - (b.price_per_sqft || 999); });
    else if (sortVal === "newest") list.sort(function (a, b) { return (b.posted_date || "").localeCompare(a.posted_date || ""); });
    return list;
  }
  function renderApartmentsAlt() {
    var container = document.getElementById("apartmentsListAlt");
    if (!container) return;
    var list = getFilteredAndSortedApartmentsAlt();
    container.innerHTML = "";
    if (!list.length) {
      container.innerHTML = "<div class=\"no-apartments\">No listings in this range. Try refreshing or adjust filters.</div>";
      return;
    }
    list.forEach(function (apt) {
      var card = document.createElement("div");
      card.className = "apartment-card";
      var badgeClass = "deal-badge";
      if (apt.deal_score >= 80) badgeClass += " excellent";
      else if (apt.deal_score >= 65) badgeClass += " good";
      else if (apt.deal_score >= 50) badgeClass += " fair";
      else badgeClass += " poor";
      var bedStr = apt.bedrooms === 0 ? "Studio" : apt.bedrooms + " bed";
      var bathStr = apt.bathrooms != null ? apt.bathrooms + " bath" : "";
      var sqftStr = apt.sqft ? apt.sqft + " sqft" : "";
      var marketHtml = "";
      if (apt.discount_pct != null && apt.discount_pct !== undefined) {
        var pct = apt.discount_pct;
        var marketLabel = pct > 0 ? Math.abs(pct).toFixed(0) + "% below market" : (pct < 0 ? Math.abs(pct).toFixed(0) + "% above market" : "At market");
        var marketCls = pct > 0 ? "positive" : (pct < 0 ? "negative" : "neutral");
        marketHtml = "<div class=\"metric\"><span class=\"metric-label\">vs Market</span><span class=\"metric-value " + marketCls + "\">" + marketLabel + "</span></div>";
      }
      var neighborhoodForMap = (apt.neighborhood || "San Francisco").trim();
      var lat = apt.latitude != null && apt.longitude != null ? Number(apt.latitude) : null;
      var lon = apt.latitude != null && apt.longitude != null ? Number(apt.longitude) : null;
      var defaultSF = [37.7849, -122.4094];
      if (lat === null || lon === null) {
        var sfNeighborhoods = { "mission": [37.7599, -122.4148], "soma": [37.7786, -122.4056], "nob hill": [37.7928, -122.4155], "nob-hill": [37.7928, -122.4155], "marina": [37.8025, -122.4364], "sunset": [37.7540, -122.5042], "richmond": [37.7804, -122.4602], "castro": [37.7609, -122.4350], "haight": [37.7699, -122.4464], "haight-ashbury": [37.7699, -122.4464], "pacific heights": [37.7912, -122.4368], "pac-heights": [37.7912, -122.4368], "inner sunset": [37.7543, -122.4650], "san francisco": [37.7849, -122.4094], "sf": [37.7849, -122.4094] };
        var key = neighborhoodForMap.toLowerCase().replace(/\s+/g, " ").trim().replace(/\s/g, "-");
        var coords = sfNeighborhoods[key] || sfNeighborhoods[key.replace(/-/g, " ")];
        if (coords) { lat = coords[0]; lon = coords[1]; } else { lat = defaultSF[0]; lon = defaultSF[1]; }
      }
      var viewUrl = ensureCraigslistListingUrl(apt.url);
      var photoBox = "";
      if (apt.thumbnail_url) {
        photoBox = "<div class=\"apt-photo-wrap\"><a href=\"" + escapeHtml(viewUrl) + "\" target=\"_blank\" rel=\"noopener noreferrer\" class=\"apt-thumbnail-link\"><img class=\"apt-thumbnail\" src=\"" + escapeHtml(apt.thumbnail_url) + "\" alt=\"Listing\" loading=\"lazy\" /></a></div>";
      } else if (lat !== null && lon !== null) {
        var bbox = (lon - 0.015).toFixed(4) + "," + (lat - 0.01).toFixed(4) + "," + (lon + 0.015).toFixed(4) + "," + (lat + 0.01).toFixed(4);
        var mapUrl = "https://www.openstreetmap.org/export/embed.html?bbox=" + encodeURIComponent(bbox) + "&layer=mapnik&marker=" + encodeURIComponent(lat + "," + lon);
        photoBox = "<div class=\"apt-map-wrap\"><iframe class=\"apt-map-iframe\" sandbox=\"allow-scripts\" title=\"Map: " + escapeHtml(neighborhoodForMap) + "\" src=\"" + escapeHtml(mapUrl) + "\" loading=\"lazy\"></iframe><div class=\"apt-map-label\">\uD83D\uDCCD " + escapeHtml(neighborhoodForMap) + ", San Francisco</div></div>";
      } else {
        var mapSearchQuery = encodeURIComponent(neighborhoodForMap + ", San Francisco, CA");
        photoBox = "<div class=\"apt-photo-placeholder apt-location-placeholder\"><span class=\"apt-photo-icon\">\uD83D\uDCCD</span><span class=\"apt-photo-text\">" + escapeHtml(neighborhoodForMap) + "</span><span class=\"apt-photo-sub\">San Francisco</span><a href=\"https://www.google.com/maps/search/?api=1&query=" + mapSearchQuery + "\" target=\"_blank\" rel=\"noopener noreferrer\" class=\"apt-map-link\">View on map</a></div>";
      }
      card.innerHTML =
        photoBox +
        "<div class=\"" + badgeClass + "\">" + (apt.deal_score != null ? apt.deal_score : 0) + "/100</div>" +
        "<div class=\"apt-header\"><h3 class=\"apt-title\">" + escapeHtml(apt.title || "Apartment Listing") + "</h3><div class=\"apt-price\">$" + (apt.price ? Number(apt.price).toLocaleString() : "0") + "/mo</div></div>" +
        "<div class=\"apt-details\"><span class=\"apt-detail\">\uD83D\uCCCD " + escapeHtml(apt.neighborhood || "Unknown") + "</span><span class=\"apt-detail\">\uD83E\uDDE1 " + bedStr + "</span>" + (bathStr ? "<span class=\"apt-detail\">\uD83D\uDEBF " + bathStr + "</span>" : "") + (sqftStr ? "<span class=\"apt-detail\">\uD83D\uDCCF " + sqftStr + "</span>" : "") + "</div>" +
        "<div class=\"apt-metrics\">" + (apt.price_per_sqft ? "<div class=\"metric\"><span class=\"metric-label\">Price/Sqft</span><span class=\"metric-value\">$" + Number(apt.price_per_sqft).toFixed(2) + "</span></div>" : "") + marketHtml + "</div>" +
        "<div class=\"apt-analysis\">\uD83E\uDD16 " + escapeHtml(apt.deal_analysis || "Analysis pending…") + "</div>" +
        "<a href=\"" + escapeHtml(viewUrl) + "\" target=\"_blank\" rel=\"noopener noreferrer\" class=\"apt-link\">View Listing \u2192</a>";
      container.appendChild(card);
    });
  }
  var refreshApartmentsAltBtn = document.getElementById("refreshApartmentsAlt");
  if (refreshApartmentsAltBtn) {
    refreshApartmentsAltBtn.addEventListener("click", function () {
      refreshApartmentsAltBtn.disabled = true;
      refreshApartmentsAltBtn.textContent = "\uD83D\uDD04 Refreshing…";
      fetch("/api/apartments/refresh", { method: "POST" })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (data.success) {
            apartmentsAltData = data.apartments || [];
            renderApartmentsAlt();
            updateApartmentStatsAlt(data.stats || {});
          }
          refreshApartmentsAltBtn.textContent = "\uD83D\uDD04 Refresh Listings";
          refreshApartmentsAltBtn.disabled = false;
        })
        .catch(function () {
          refreshApartmentsAltBtn.textContent = "\uD83D\uDD04 Try Again";
          refreshApartmentsAltBtn.disabled = false;
        });
    });
  }
  var neighborhoodFilterAlt = document.getElementById("neighborhoodFilterAlt");
  var bedroomFilterAlt = document.getElementById("bedroomFilterAlt");
  var sortByAlt = document.getElementById("sortByAlt");
  if (neighborhoodFilterAlt) neighborhoodFilterAlt.addEventListener("change", function () { renderApartmentsAlt(); });
  if (bedroomFilterAlt) bedroomFilterAlt.addEventListener("change", function () { renderApartmentsAlt(); });
  if (sortByAlt) sortByAlt.addEventListener("change", function () { renderApartmentsAlt(); });

  // --- Stanford Area Listings (alternate) ---
  var stanfordApartmentsAltData = [];
  function loadStanfordApartmentsAlt() {
    var btn = document.getElementById("refreshStanfordApartmentsAlt");
    if (!btn) return;
    btn.disabled = true;
    btn.textContent = "\uD83D\uDD04 Loading…";
    fetch("/api/apartments/stanford")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.error) throw new Error(data.error);
        stanfordApartmentsAltData = data.apartments || [];
        renderStanfordApartmentsAlt();
        updateStanfordApartmentStatsAlt(data.stats || {});
        btn.textContent = "\uD83D\uDD04 Refresh Listings";
        btn.disabled = false;
      })
      .catch(function (err) {
        console.error("Error loading alternate Stanford listings:", err);
        var list = document.getElementById("stanfordApartmentsListAlt");
        if (list) list.innerHTML = "<div class=\"error-message\">Error loading listings. Please try again.</div>";
        btn.textContent = "\uD83D\uDD04 Try Again";
        btn.disabled = false;
      });
  }
  function updateStanfordApartmentStatsAlt(stats) {
    var totalEl = document.getElementById("stanfordTotalListingsAlt");
    var excellentEl = document.getElementById("stanfordExcellentDealsAlt");
    var avgEl = document.getElementById("stanfordAvgPriceAlt");
    if (totalEl) totalEl.textContent = stats.total || 0;
    if (excellentEl) excellentEl.textContent = stats.excellent_deals || 0;
    if (avgEl) avgEl.textContent = stats.average_price ? "$" + Number(stats.average_price).toLocaleString() : "$0";
  }
  function getFilteredAndSortedStanfordApartmentsAlt() {
    var hoodFilter = document.getElementById("stanfordNeighborhoodFilterAlt");
    var bedFilter = document.getElementById("stanfordBedroomFilterAlt");
    var sortBy = document.getElementById("stanfordSortByAlt");
    var list = stanfordApartmentsAltData.slice();
    var hoodVal = hoodFilter ? hoodFilter.value : "all";
    var bedVal = bedFilter ? bedFilter.value : "all";
    var sortVal = sortBy ? sortBy.value : "best-deal";
    if (hoodVal !== "all") list = list.filter(function (apt) { var slug = neighborhoodSlug(apt.neighborhood); return slug === hoodVal || slug.indexOf(hoodVal) !== -1; });
    if (bedVal !== "all") list = list.filter(function (apt) { var b = apt.bedrooms; if (bedVal === "studio") return b === 0; if (bedVal === "3") return b >= 3; return b === parseInt(bedVal, 10); });
    if (sortVal === "best-deal") list.sort(function (a, b) { return (b.deal_score || 0) - (a.deal_score || 0); });
    else if (sortVal === "price-low") list.sort(function (a, b) { return (a.price || 0) - (b.price || 0); });
    else if (sortVal === "price-sqft") list.sort(function (a, b) { return (a.price_per_sqft || 999) - (b.price_per_sqft || 999); });
    else if (sortVal === "newest") list.sort(function (a, b) { return (b.posted_date || "").localeCompare(a.posted_date || ""); });
    return list;
  }
  function renderStanfordApartmentsAlt() {
    var container = document.getElementById("stanfordApartmentsListAlt");
    if (!container) return;
    var list = getFilteredAndSortedStanfordApartmentsAlt();
    container.innerHTML = "";
    if (!list.length) {
      container.innerHTML = "<div class=\"no-apartments\">No listings in this range. Try refreshing or adjust filters.</div>";
      return;
    }
    list.forEach(function (apt) {
      var card = document.createElement("div");
      card.className = "apartment-card";
      var badgeClass = "deal-badge " + (apt.deal_score >= 80 ? "excellent" : apt.deal_score >= 65 ? "good" : apt.deal_score >= 50 ? "fair" : "poor");
      var bedStr = apt.bedrooms === 0 ? "Studio" : apt.bedrooms + " bed";
      var bathStr = apt.bathrooms != null ? apt.bathrooms + " bath" : "";
      var sqftStr = apt.sqft ? apt.sqft + " sqft" : "";
      var neighborhoodForMap = (apt.neighborhood || "Palo Alto").trim();
      var coords = stanfordCoordsFromNeighborhood(neighborhoodForMap);
      var lat = apt.latitude != null && apt.longitude != null ? Number(apt.latitude) : coords[0];
      var lon = apt.latitude != null && apt.longitude != null ? Number(apt.longitude) : coords[1];
      var viewUrl = ensureCraigslistListingUrl(apt.url);
      var bbox = (lon - 0.015).toFixed(4) + "," + (lat - 0.01).toFixed(4) + "," + (lon + 0.015).toFixed(4) + "," + (lat + 0.01).toFixed(4);
      var mapUrl = "https://www.openstreetmap.org/export/embed.html?bbox=" + encodeURIComponent(bbox) + "&layer=mapnik&marker=" + encodeURIComponent(lat + "," + lon);
      var photoBox = "<div class=\"apt-map-wrap\"><iframe class=\"apt-map-iframe\" sandbox=\"allow-scripts\" title=\"Map: " + escapeHtml(neighborhoodForMap) + "\" src=\"" + escapeHtml(mapUrl) + "\" loading=\"lazy\"></iframe><div class=\"apt-map-label\">\uD83D\uDCCD " + escapeHtml(neighborhoodForMap) + "</div></div>";
      var marketHtml = (apt.discount_pct != null && apt.discount_pct !== undefined) ? "<div class=\"metric\"><span class=\"metric-label\">vs Market</span><span class=\"metric-value " + (apt.discount_pct > 0 ? "positive" : apt.discount_pct < 0 ? "negative" : "neutral") + "\">" + (apt.discount_pct > 0 ? Math.abs(apt.discount_pct).toFixed(0) + "% below market" : apt.discount_pct < 0 ? Math.abs(apt.discount_pct).toFixed(0) + "% above market" : "At market") + "</span></div>" : "";
      card.innerHTML =
        photoBox +
        "<div class=\"" + badgeClass + "\">" + (apt.deal_score != null ? apt.deal_score : 0) + "/100</div>" +
        "<div class=\"apt-header\"><h3 class=\"apt-title\">" + escapeHtml(apt.title || "Apartment Listing") + "</h3><div class=\"apt-price\">$" + (apt.price ? Number(apt.price).toLocaleString() : "0") + "/mo</div></div>" +
        "<div class=\"apt-details\"><span class=\"apt-detail\">\uD83D\uCCCD " + escapeHtml(apt.neighborhood || "Unknown") + "</span><span class=\"apt-detail\">\uD83E\uDDE1 " + bedStr + "</span>" + (bathStr ? "<span class=\"apt-detail\">\uD83D\uDEBF " + bathStr + "</span>" : "") + (sqftStr ? "<span class=\"apt-detail\">\uD83D\uDCCF " + sqftStr + "</span>" : "") + "</div>" +
        "<div class=\"apt-metrics\">" + (apt.price_per_sqft ? "<div class=\"metric\"><span class=\"metric-label\">Price/Sqft</span><span class=\"metric-value\">$" + Number(apt.price_per_sqft).toFixed(2) + "</span></div>" : "") + marketHtml + "</div>" +
        "<div class=\"apt-analysis\">\uD83E\uDD16 " + escapeHtml(apt.deal_analysis || "Analysis pending…") + "</div>" +
        "<a href=\"" + escapeHtml(viewUrl) + "\" target=\"_blank\" rel=\"noopener noreferrer\" class=\"apt-link\">View Listing \u2192</a>";
      container.appendChild(card);
    });
  }
  var refreshStanfordAltBtn = document.getElementById("refreshStanfordApartmentsAlt");
  if (refreshStanfordAltBtn) {
    refreshStanfordAltBtn.addEventListener("click", function () {
      refreshStanfordAltBtn.disabled = true;
      refreshStanfordAltBtn.textContent = "\uD83D\uDD04 Refreshing…";
      fetch("/api/apartments/stanford/refresh", { method: "POST" })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (data.success) {
            stanfordApartmentsAltData = data.apartments || [];
            renderStanfordApartmentsAlt();
            updateStanfordApartmentStatsAlt(data.stats || {});
          }
          refreshStanfordAltBtn.textContent = "\uD83D\uDD04 Refresh Listings";
          refreshStanfordAltBtn.disabled = false;
        })
        .catch(function () {
          refreshStanfordAltBtn.textContent = "\uD83D\uDD04 Try Again";
          refreshStanfordAltBtn.disabled = false;
        });
    });
  }
  var stanfordNeighborhoodFilterAlt = document.getElementById("stanfordNeighborhoodFilterAlt");
  var stanfordBedroomFilterAlt = document.getElementById("stanfordBedroomFilterAlt");
  var stanfordSortByAlt = document.getElementById("stanfordSortByAlt");
  if (stanfordNeighborhoodFilterAlt) stanfordNeighborhoodFilterAlt.addEventListener("change", function () { renderStanfordApartmentsAlt(); });
  if (stanfordBedroomFilterAlt) stanfordBedroomFilterAlt.addEventListener("change", function () { renderStanfordApartmentsAlt(); });
  if (stanfordSortByAlt) stanfordSortByAlt.addEventListener("change", function () { renderStanfordApartmentsAlt(); });
})();
