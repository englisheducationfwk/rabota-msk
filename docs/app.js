/* Работа MSK — страница: карточки, фильтры, избранное, блокировка.
   Данные — data/vacancies.json (локально) или ветка data на GitHub.
   Всё «моё» (избранное, скрытые, блокировки, заметки, скролл) живёт
   на телефоне в localStorage и никуда не отправляется. */

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
    filters: { new: false, unofficial: false, fav: false },
    salaryMin: 0,
    q: "",
    expanded: {},
    lastVisit: LS.get("msk_last_visit", 0)
  };
  var fav = LS.get("msk_fav", {});
  var hidden = LS.get("msk_hidden", {});
  var blocked = LS.get("msk_blocked", {});   // работодатели «в бан»
  var notes = LS.get("msk_notes", {});
  var noted = LS.get("msk_noted", {});
  var scrollY = LS.get("msk_scroll_y", 0);

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
    refreshBtn: document.getElementById("refresh-btn"),
    toTop: document.getElementById("to-top")
  };

  /* 📱 Страховка от «версии для ПК»: если это телефон, а вьюпорт почему-то
     широкий (Safari запомнил «Сайт для ПК» или кривой вебвью), показываем
     подсказку, как вернуть мобильный вид. Длинные строки в это время уже
     не растягивают страницу — за это отвечает CSS (overflow-x: clip). */
  (function pcHint() {
    var ua = navigator.userAgent || "";
    var isPhone = /iPhone|iPod|Android/i.test(ua);
    if (!isPhone || window.innerWidth <= 700) return;
    var hint = document.createElement("div");
    hint.className = "pc-hint";
    hint.innerHTML = "Похоже, открылся «сайт для ПК». В Safari нажмите "
      + "<b>«аА»</b> в адресной строке → <b>«Версия для мобильного»</b> — "
      + "и страница станет удобной.";
    document.body.insertBefore(hint, document.body.firstChild);
  })();

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
    var min = Math.floor(Date.now() / 1000 - ts) / 60;
    min = Math.floor(min);
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
    var hm = ("0" + dt.getHours()).slice(-2) + ":" +
             ("0" + dt.getMinutes()).slice(-2);
    if (dt.toDateString() === today.toDateString()) return "сегодня в " + hm;
    return dt.getDate() + "." + ("0" + (dt.getMonth() + 1)).slice(-2) +
           " в " + hm;
  }
  function money(n) {
    return String(Math.round(n)).replace(/\B(?=(\d{3})+(?!\d))/g, " ");
  }
  function isRubleSalary(unit) { return unit && unit !== "месяц" && unit !== ""; }
  function blockKey(it) {
    return it.employer_id ? "id:" + it.employer_id :
           (it.employer ? "name:" + String(it.employer).toLowerCase() : "v:" + it.id);
  }
  function blockLabel(it) {
    return it.employer || it.title || "работодатель";
  }

  /* --- данные ---
     Источники по очереди:
     1) соседний файл (локальный предпросмотр с компьютера);
     2) GitHub API — самый свежий (кэш минуту, после публикации сразу видно);
     3) raw.githubusercontent — запасной (CDN может держать старую копию).
     Если переименуете репозиторий — поправьте адреса ниже. */
  var REPO = "englisheducationfwk/rabota-msk";
  var RAW_DATA = "https://raw.githubusercontent.com/" + REPO +
                 "/data/vacancies.json";
  var API_DATA = "https://api.github.com/repos/" + REPO +
                 "/contents/vacancies.json?ref=data";
  var SOURCES = [
    { url: API_DATA, headers: { "Accept": "application/vnd.github.raw+json" } },
    { url: "data/vacancies.json" },
    { url: RAW_DATA }
  ];

  function fetchData() {
    tryNext(0);
  }

  function tryNext(i) {
    if (i >= SOURCES.length) {
      el.updated.textContent = state.items.length
        ? "Нет связи — показываю последние данные"
        : "Ждём первые вакансии — появятся после первого сбора";
      render("refresh");
      return;
    }
    var src = SOURCES[i];
    var url = src.url + (src.url.indexOf("?") === -1 ? "?" : "&") +
              "t=" + Date.now();
    fetch(url, { cache: "no-store", headers: src.headers || {} })
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function (d) {
        if (!d || !d.items) throw new Error("пусто");
        state.items = d.items;
        state.updated = d.updated || 0;
        render("refresh");
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
      if (blocked[blockKey(it)]) return false;
      if (hidden[it.id] && !state.filters.fav) return false;
      if (state.filters.fav && !fav[it.id]) return false;
      if (state.filters.new && !(it.first_seen > state.lastVisit)) return false;
      if (state.filters.unofficial && !it.unofficial) return false;
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
  function render(mode) {
    var keepY = (mode === "refresh") ? (window.scrollY || 0) : 0;
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

    var blockedCount = Object.keys(blocked).length;
    var old = document.getElementById("unblock-chip");
    if (old) old.remove();
    if (blockedCount > 0) {
      var b = document.createElement("button");
      b.className = "chip block-chip";
      b.id = "unblock-chip";
      b.textContent = "⛔ Разблокировать (" + blockedCount + ")";
      b.addEventListener("click", function () {
        if (!confirm("Вернуть заблокированных работодателей (" +
                     blockedCount + ")? Их вакансии снова появятся.")) return;
        blocked = {};
        LS.set("msk_blocked", blocked);
        render("user");
      });
      el.chips.appendChild(b);
    }

    el.empty.hidden = items.length > 0;
    el.list.innerHTML = "";
    items.forEach(function (it) {
      el.list.appendChild(card(it));
    });
    if (mode === "refresh" && keepY > 40) {
      window.scrollTo(0, keepY);
    } else if (mode === "user") {
      window.scrollTo(0, 0);
    }
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

    // когда опубликовано: точная дата от Авито + насколько давно
    var when = "";
    if (it.published_text) {
      when = "🕐 опубликовано " + esc(it.published_text) +
             (it.published ? " (" + esc(ago(it.published)) + ")" : "");
    } else if (it.published) {
      when = "🕐 опубликовано " + esc(timeStr(it.published)) +
             " (" + esc(ago(it.published)) + ")";
    } else if (it.first_seen) {
      when = "🕐 найдено " + esc(ago(it.first_seen));
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
      (when ? '<div class="fresh">' + when + "</div>" : "") +
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
        '<button class="act block-act" data-block="' + esc(blockKey(it)) +
          '" data-block-label="' + esc(blockLabel(it)) +
          '">⛔ Заблокировать</button>' +
        '<a class="act open" href="' + esc(it.url) +
          '" target="_blank" rel="noopener">Открыть на Авито</a>' +
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
    if (t.hasAttribute("data-block")) {
      var key = t.getAttribute("data-block");
      var label = t.getAttribute("data-block-label") || "работодателя";
      if (confirm("Заблокировать «" + label + "»?\n\nВсе вакансии от него " +
                  "исчезнут из списка — и текущие, и будущие.\n" +
                  "Вернуть можно кнопкой «Разблокировать» сверху.")) {
        blocked[key] = label;
        LS.set("msk_blocked", blocked);
        render("user");
      }
      return;
    }
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
    var y = window.scrollY;
    render("keep");
    window.scrollTo(0, y);
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
    render("user");
  });

  el.chips.addEventListener("click", function (ev) {
    var b = ev.target;
    if (b.tagName !== "BUTTON" || !b.hasAttribute("data-filter")) return;
    var key = b.getAttribute("data-filter");
    state.filters[key] = !state.filters[key];
    b.classList.toggle("on", state.filters[key]);
    render("user");
  });

  el.newBtn.addEventListener("click", function () {
    state.filters.new = true;
    var chip = el.chips.querySelector('[data-filter="new"]');
    if (chip) chip.classList.add("on");
    render("user");
  });

  el.salary.addEventListener("change", function () {
    state.salaryMin = parseInt(el.salary.value, 10) || 0;
    render("user");
  });

  var searchTimer = null;
  el.search.addEventListener("input", function () {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(function () {
      state.q = el.search.value;
      render("user");
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

  /* --- скролл: помним где остановилась + кнопка «наверх» --- */
  var scrollTimer = null;
  window.addEventListener("scroll", function () {
    clearTimeout(scrollTimer);
    scrollTimer = setTimeout(function () {
      LS.set("msk_scroll_y", window.scrollY || 0);
    }, 250);
    el.toTop.hidden = (window.scrollY || 0) < 600;
  }, { passive: true });

  el.toTop.addEventListener("click", function () {
    window.scrollTo({ top: 0, behavior: "smooth" });
    LS.set("msk_scroll_y", 0);
  });

  /* --- старт --- */
  fetchData();
  // восстановить позицию прошлого визита после первой отрисовки
  setTimeout(function () {
    var y = LS.get("msk_scroll_y", 0);
    if (y > 100) { window.scrollTo(0, y); }
  }, 700);
  // обновляем данные раз в 5 минут (и при каждом возврате на страницу)
  setInterval(fetchData, 5 * 60 * 1000);
  document.addEventListener("visibilitychange", function () {
    if (!document.hidden) fetchData();
  });
})();
