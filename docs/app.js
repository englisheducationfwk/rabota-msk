/* 🧹 Работа MSK — страница мамы: карточки вакансий, фильтры, избранное.
   Данные тянет из data/vacancies.json (рядом, тот же домен — CORS не мешает).
   Всё «моё» (избранное, скрытые, заметки, когда заходила) живёт на телефоне
   в localStorage и никуда не отправляется. */

(function () {
  "use strict";

  var LS = {
    get: function (k, d) {
      try { var v = localStorage.getItem(k); return v ? JSON.parse(v) : d; }
      catch (e) { return d; }
    },
    set: function (k, v) {
      try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {}
    }
  };

  var state = {
    items: [],
    updated: 0,
    sort: "score",
    filters: { new: false, unofficial: false, housing: false, fav: false },
    salaryMin: 0,
    q: "",
    expanded: {},
    lastVisit: LS.get("msk_last_visit", 0)
  };
  var fav = LS.get("msk_fav", {});
  var hidden = LS.get("msk_hidden", {});
  var notes = LS.get("msk_notes", {});
  var noted = LS.get("msk_noted", {});

  var el = {
    list: document.getElementById("list"),
    empty: document.getElementById("empty"),
    updated: document.getElementById("updated"),
    newBar: document.getElementById("new-bar"),
    newCount: document.getElementById("new-count"),
    newBtn: document.getElementById("new-btn"),
    search: document.getElementById("search"),
    seg: document.getElementById("sort-seg"),
    chips: document.getElementById("filter-chips"),
    salary: document.getElementById("salary-min"),
    themeBtn: document.getElementById("theme-btn"),
    refreshBtn: document.getElementById("refresh-btn")
  };

  /* --- утилиты --- */
  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }
  function plural(n, one, few, many) {
    var m10 = n % 10, m100 = n % 100;
    if (m10 === 1 && m100 !== 11) return one;
    if (m10 >= 2 && m10 <= 4 && (m100 < 10 || m100 >= 20)) return few;
    return many;
  }
  function ago(ts) {
    if (!ts) return "";
    var min = Math.floor((Date.now() / 1000 - ts) / 60);
    if (min < 1) return "только что";
    if (min < 60) return min + " " + plural(min, "минуту", "минуты", "минут") + " назад";
    var h = Math.floor(min / 60);
    if (h < 24) return h + " " + plural(h, "час", "часа", "часов") + " назад";
    var d = Math.floor(h / 24);
    if (d === 1) return "вчера";
    return d + " " + plural(d, "день", "дня", "дней") + " назад";
  }
  function timeStr(ts) {
    if (!ts) return "";
    var dt = new Date(ts * 1000);
    var today = new Date();
    var sameDay = dt.toDateString() === today.toDateString();
    var hm = ("0" + dt.getHours()).slice(-2) + ":" +
             ("0" + dt.getMinutes()).slice(-2);
    if (sameDay) return "сегодня в " + hm;
    return dt.getDate() + "." + ("0" + (dt.getMonth() + 1)).slice(-2) +
           " в " + hm;
  }
  function money(n) {
    return String(Math.round(n)).replace(/\B(?=(\d{3})+(?!\d))/g, " ");
  }
  function isRubleSalary(unit) { return unit && unit !== "месяц" && unit !== ""; }

  /* --- данные ---
     Два источника по очереди: сначала соседний файл (локальный
     предпросмотр с компьютера), потом — свежий JSON из ветки данных
     на GitHub (его каждые 15 минут обновляет компьютер).
     Если переименуете репозиторий — поправьте адрес ниже. */
  var RAW_DATA = "https://raw.githubusercontent.com/englisheducationfwk/" +
                 "rabota-msk/data/vacancies.json";
  var SOURCES = ["data/vacancies.json", RAW_DATA];

  function fetchData() {
    tryNext(0);
  }

  function tryNext(i) {
    if (i >= SOURCES.length) {
      el.updated.textContent = state.items.length
        ? "Нет связи — показываю последние данные"
        : "Ждём первые вакансии — они появятся после первого сбора";
      render();
      return;
    }
    var url = SOURCES[i] + (SOURCES[i].indexOf("?") === -1 ? "?" : "&") +
              "t=" + Date.now();
    fetch(url, { cache: "no-store" })
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function (d) {
        if (!d || !d.items) throw new Error("пусто");
        state.items = d.items;
        state.updated = d.updated || 0;
        render();
        el.updated.textContent = state.updated
          ? ("Обновлено " + timeStr(state.updated) +
             " · вакансий: " + state.items.length)
          : "Данные ещё не приехали";
      })
      .catch(function () { tryNext(i + 1); });
  }

  /* --- фильтры и сортировка --- */
  function visibleItems() {
    var q = state.q.trim().toLowerCase();
    var out = state.items.filter(function (it) {
      if (hidden[it.id] && !state.filters.fav) return false;
      if (state.filters.fav && !fav[it.id]) return false;
      if (state.filters.new && !(it.first_seen > state.lastVisit)) return false;
      if (state.filters.unofficial && !it.unofficial) return false;
      if (state.filters.housing && !it.housing) return false;
      if (state.salaryMin && (it.salary_month || 0) < state.salaryMin)
        return false;
      if (q) {
        var hay = [it.title, it.employer, it.metro, it.address, it.description]
          .join(" ").toLowerCase();
        if (hay.indexOf(q) === -1) return false;
      }
      return true;
    });
    var by = {
      score: function (a, b) { return (b.score || 0) - (a.score || 0); },
      salary: function (a, b) {
        return (b.salary_month || 0) - (a.salary_month || 0);
      },
      fresh: function (a, b) { return (b.first_seen || 0) - (a.first_seen || 0); },
      rating: function (a, b) {
        var ra = (a.rating && a.rating.score) || 0;
        var rb = (b.rating && b.rating.score) || 0;
        return rb - ra;
      }
    };
    return out.sort(by[state.sort] || by.score);
  }

  /* --- отрисовка --- */
  function render() {
    var items = visibleItems();
    var freshCount = state.items.filter(function (it) {
      return it.first_seen > state.lastVisit;
    }).length;
    if (freshCount > 0 && state.lastVisit > 0) {
      el.newBar.hidden = false;
      el.newCount.textContent = freshCount;
    } else {
      el.newBar.hidden = true;
    }

    el.empty.hidden = items.length > 0;
    el.list.innerHTML = "";
    items.forEach(function (it) {
      el.list.appendChild(card(it));
    });
    // отметить визит: следующее «Новых» считается от этого момента
    LS.set("msk_last_visit", Math.floor(Date.now() / 1000));
  }

  function card(it) {
    var wrap = document.createElement("article");
    wrap.className = "card" + (it.first_seen > state.lastVisit &&
                               state.lastVisit > 0 ? " is-new" : "");

    var score = it.score || 0;
    var cls = score >= 70 ? "hi" : (score >= 45 ? "mid" : "lo");

    var badges = [];
    if (it.unofficial) badges.push('<span class="badge hot">🔥 без оформления</span>');
    if (it.housing) badges.push('<span class="badge">🏠 с проживанием</span>');
    if (it.status === "new") badges.push('<span class="badge new-b">✨ новая</span>');

    var rating = "";
    if (it.rating && it.rating.score) {
      rating = '<span class="stars">★ ' + it.rating.score + "</span> (" +
        (it.rating.reviews || 0) + " " +
        plural(it.rating.reviews || 0, "отзыв", "отзыва", "отзывов") + ")";
    }

    var priceMain = it.price ? esc(it.price) : "з/п не указана";
    var approx = "";
    if (it.salary_month && isRubleSalary(it.salary_unit)) {
      approx = ' <span class="approx">≈ ' + money(it.salary_month) +
               " ₽/мес</span>";
    }

    var descCls = state.expanded[it.id] ? "desc" : "desc clip";
    var reasons = (it.reasons || []).map(function (r) {
      var s = String(r);
      var cls2 = s.charAt(0) === "+" ? "up" : (s.charAt(0) === "-" ? "down" : "");
      return '<li class="' + cls2 + '">' + esc(s) + "</li>";
    }).join("");

    wrap.innerHTML =
      '<div class="card-top">' +
        '<h2 class="card-title">' + esc(it.title || "Вакансия") + "</h2>" +
        '<div class="score ' + cls + '">' + score + "<small>выгода</small></div>" +
      "</div>" +
      '<div class="price">' + priceMain + approx + "</div>" +
      (badges.length ? '<div class="badges">' + badges.join("") + "</div>" : "") +
      (it.employer ? '<div class="emp">🏢 ' + esc(it.employer) +
        (rating ? " · " + rating : "") + "</div>" : "") +
      (it.metro || it.address
        ? '<div class="addr">📍 ' + esc(it.metro || it.address) + "</div>"
        : "") +
      (it.published || it.first_seen
        ? '<div class="fresh">🕐 ' +
          esc(ago(it.published || it.first_seen)) + "</div>"
        : "") +
      (it.description
        ? '<div class="' + descCls + '">' + esc(it.description) + "</div>" +
          '<button class="more-btn" data-more="' + esc(it.id) + '">' +
          (state.expanded[it.id] ? "Свернуть" : "Показать описание") + "</button>"
        : "") +
      (reasons ? '<div class="reasons"><b>Почему такая оценка:</b><ul>' +
        reasons + "</ul></div>" : "") +
      '<div class="actions">' +
        '<button class="act' + (fav[it.id] ? " on" : "") + '" data-fav="' +
          esc(it.id) + '">' + (fav[it.id] ? "❤️ В избранном" : "🤍 В избранное") +
        "</button>" +
        '<button class="act' + (noted[it.id] ? " on" : "") + '" data-note="' +
          esc(it.id) + '">📝 Заметка</button>' +
        '<button class="act hide-act' + (hidden[it.id] ? " on" : "") +
          '" data-hide="' + esc(it.id) + '">' +
          (hidden[it.id] ? "↩️ Показать" : "🚫 Не подходит") + "</button>" +
        '<a class="act open" style="text-align:center;text-decoration:none" ' +
          'href="' + esc(it.url) + '" target="_blank" rel="noopener">' +
          "Открыть</a>" +
      "</div>" +
      '<textarea class="note' + (noted[it.id] ? " show" : "") + '" ' +
        'data-notefield="' + esc(it.id) + '" placeholder="Заметка (видна ' +
        'только вам)">' + esc(notes[it.id] || "") + "</textarea>";

    return wrap;
  }

  /* --- события --- */
  el.list.addEventListener("click", function (ev) {
    var t = ev.target;
    if (!t || t.tagName !== "BUTTON") return;
    var id = t.getAttribute("data-fav") || t.getAttribute("data-hide") ||
             t.getAttribute("data-note") || t.getAttribute("data-more");
    if (!id) return;

    if (t.hasAttribute("data-fav")) {
      if (fav[id]) { delete fav[id]; } else { fav[id] = 1; }
      LS.set("msk_fav", fav);
    } else if (t.hasAttribute("data-hide")) {
      if (hidden[id]) { delete hidden[id]; } else { hidden[id] = 1; }
      LS.set("msk_hidden", hidden);
    } else if (t.hasAttribute("data-note")) {
      noted[id] = noted[id] ? 0 : 1;
      LS.set("msk_noted", noted);
    } else if (t.hasAttribute("data-more")) {
      state.expanded[id] = !state.expanded[id];
    }
    render();
  });

  el.list.addEventListener("input", function (ev) {
    var t = ev.target;
    if (t && t.hasAttribute && t.hasAttribute("data-notefield")) {
      var id = t.getAttribute("data-notefield");
      notes[id] = t.value;
      LS.set("msk_notes", notes);
    }
  });

  el.seg.addEventListener("click", function (ev) {
    var b = ev.target;
    if (b.tagName !== "BUTTON") return;
    state.sort = b.getAttribute("data-sort");
    Array.prototype.forEach.call(el.seg.children, function (c) {
      c.classList.toggle("on", c === b);
    });
    render();
  });

  el.chips.addEventListener("click", function (ev) {
    var b = ev.target;
    if (b.tagName !== "BUTTON" || !b.hasAttribute("data-filter")) return;
    var key = b.getAttribute("data-filter");
    state.filters[key] = !state.filters[key];
    b.classList.toggle("on", state.filters[key]);
    if (key === "fav") state.updated = state.updated; // ничего, просто ререндер
    render();
  });

  el.newBtn.addEventListener("click", function () {
    state.filters.new = true;
    var chip = el.chips.querySelector('[data-filter="new"]');
    if (chip) chip.classList.add("on");
    render();
    window.scrollTo(0, 0);
  });

  el.salary.addEventListener("change", function () {
    state.salaryMin = parseInt(el.salary.value, 10) || 0;
    render();
  });

  var searchTimer = null;
  el.search.addEventListener("input", function () {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(function () {
      state.q = el.search.value;
      render();
    }, 200);
  });

  /* --- тема --- */
  var theme = LS.get("msk_theme", "dark");
  function applyTheme(t) {
    document.documentElement.setAttribute("data-theme", t);
    el.themeBtn.textContent = t === "dark" ? "🌙" : "☀️";
  }
  applyTheme(theme);
  el.themeBtn.addEventListener("click", function () {
    theme = theme === "dark" ? "light" : "dark";
    LS.set("msk_theme", theme);
    applyTheme(theme);
  });

  el.refreshBtn.addEventListener("click", function () {
    el.refreshBtn.textContent = "⏳";
    fetchData();
    setTimeout(function () { el.refreshBtn.textContent = "🔄"; }, 900);
  });

  /* --- старт: грузим сразу и потом раз в 3 минуты --- */
  fetchData();
  setInterval(fetchData, 3 * 60 * 1000);
  document.addEventListener("visibilitychange", function () {
    if (!document.hidden) fetchData();
  });
})();
