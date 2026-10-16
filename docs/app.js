/* Работа MSK — страница: два меню (Новые / Просмотренные), порции по 30,
   отметка «просмотрено», фильтры, избранное, блокировка.
   Данные — data/vacancies.json (локально) или ветка data на GitHub.
   Всё «моё» (просмотрено, избранное, скрытые, блокировки, заметки, скролл)
   живёт на телефоне в localStorage и никуда не отправляется. */

(function () {
  "use strict";

  var PER = 30;      // сколько карточек рисуем за раз
  var DWELL = 400;   // мс в кадре — и карточка считается просмотренной
  var TAB_SORT = { "new": "fresh", seen: "score" };

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
    sig: "",
    tab: "new",                                  // new | seen
    sort: TAB_SORT["new"],
    filters: { unofficial: false, fav: false },
    salaryMin: 0,
    q: "",
    expanded: {},
    page: 1
  };
  var viewed = LS.get("msk_viewed", {});   // id → когда пролистали
  var fav = LS.get("msk_fav", {});
  var hidden = LS.get("msk_hidden", {});
  var blocked = LS.get("msk_blocked", {});   // работодатели «в бан»
  var notes = LS.get("msk_notes", {});
  var noted = LS.get("msk_noted", {});
  var scrollY = LS.get("msk_scroll_y", 0);
  /* Карточки, уже показанные в текущем списке: пока список не перестроен
     (перезаход, смена меню/фильтра/сортировки, 🔄) — они остаются на месте,
     даже если их только что пометили просмотренными. Список не дёргается. */
  var pinned = {};

  var el = {
    list: document.getElementById("list"),
    empty: document.getElementById("empty"),
    emptyIcon: document.getElementById("empty-icon"),
    emptyTitle: document.getElementById("empty-title"),
    emptyText: document.getElementById("empty-text"),
    updated: document.getElementById("updated"),
    newBar: document.getElementById("new-bar"),
    newCount: document.getElementById("new-count"),
    newBtn: document.getElementById("new-btn"),
    tabs: document.getElementById("tabs"),
    cntNew: document.getElementById("cnt-new"),
    cntSeen: document.getElementById("cnt-seen"),
    more: document.getElementById("more-btn"),
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
  function nowSec() { return Math.floor(Date.now() / 1000); }
  function cardOf(node) {
    var n = node;
    while (n && n.classList && !n.classList.contains("card")) n = n.parentNode;
    return (n && n.classList && n.classList.contains("card")) ? n : null;
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

  function signature(items) {
    return items.map(function (it) {
      return it.id + ":" + (it.score || 0) + ":" + (it.last_seen || 0);
    }).join(",");
  }

  function tryNext(i) {
    if (i >= SOURCES.length) {
      el.updated.textContent = state.items.length
        ? "Нет связи — показываю последние данные"
        : "Ждём первые вакансии — появятся после первого сбора";
      render("keep");
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
        var sig = signature(d.items);
        var changed = sig !== state.sig;
        state.items = d.items;
        state.updated = d.updated || 0;
        state.sig = sig;
        /* Если данные те же — список не пересобираем: нечего тревожить. */
        if (changed || !state.items.length) render("keep");
        updateHead();
      })
      .catch(function () { tryNext(i + 1); });
  }

  function updateHead() {
    el.updated.textContent = state.updated
      ? ("Собрано " + timeStr(state.updated) +
         " · вакансий: " + state.items.length)
      : "Данные ещё не приехали";
  }

  /* --- фильтры, меню и сортировка --- */
  function isViewed(it) { return !!viewed[it.id]; }

  /* Всё, что отсеивается независимо от меню: скрытые, блок, поиск, чипы. */
  function baseFiltered() {
    var q = state.q.trim().toLowerCase();
    return state.items.filter(function (it) {
      if (blocked[blockKey(it)]) return false;
      if (hidden[it.id] && !state.filters.fav) return false;
      if (state.filters.fav && !fav[it.id]) return false;
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
  }

  /* В каком меню карточка: «Новые» — которых ещё не пролистали,
     «Просмотренные» — остальные. Уже показанные в списке (pinned) держим
     на месте, пока список не перестроят. */
  function inTab(it) {
    if (pinned[it.id]) return true;
    return state.tab === "new" ? !isViewed(it) : isViewed(it);
  }

  function visibleItems() {
    var out = baseFiltered().filter(inTab);
    var by = {
      score: function (a, b) { return (b.score || 0) - (a.score || 0); },
      salary: function (a, b) {
        return (b.salary_month || 0) - (a.salary_month || 0);
      },
      fresh: function (a, b) {
        return (b.first_seen || 0) - (a.first_seen || 0);
      },
      rating: function (a, b) {
        var ra = (a.rating && a.rating.score) || 0;
        var rb = (b.rating && b.rating.score) || 0;
        return rb - ra;
      }
    };
    return out.sort(by[state.sort] || by.score);
  }

  function setSortUI() {
    Array.prototype.forEach.call(el.seg.children, function (c) {
      c.classList.toggle("on", c.getAttribute("data-sort") === state.sort);
    });
  }

  /* Счётчики меню и полоса «Новых: N» — по всему найденному (с поиском
     и фильтрами), но без учёта самого меню. */
  function updateCounts() {
    var filtered = baseFiltered();
    var n = 0;
    filtered.forEach(function (it) { if (!isViewed(it)) n++; });
    el.cntNew.textContent = n;
    el.cntSeen.textContent = filtered.length - n;

    var unviewed = 0;
    state.items.forEach(function (it) { if (!isViewed(it)) unviewed++; });
    /* Полосу держим только когда она что-то добавляет: на меню «Новые»
       счётчик и так виден на вкладке. */
    if (unviewed > 0 && state.tab !== "new") {
      el.newBar.hidden = false;
      el.newCount.textContent = unviewed;
    } else {
      el.newBar.hidden = true;
    }
  }

  /* --- отметка «просмотрено» --- */
  var io = null;
  /* Пока палец на экране — карточки не помечаем: значок ✅ дорисовывается в
     карточку и сдвигает кнопки, а нажатие не должно уезжать из-под пальца.
     Как палец ушёл — пересматриваем кадр и метим (ещё раз через DWELL). */
  var pointerBusy = false;
  document.addEventListener("pointerdown", function () { pointerBusy = true; });
  document.addEventListener("pointercancel", function () { pointerBusy = false; });
  document.addEventListener("pointerup", function () {
    pointerBusy = false;
    observeCards();
  });

  function setCardViewed(node, on) {
    if (!node) return;
    node.classList.toggle("is-viewed", !!on);
    var btn = node.querySelector(".seen-act");
    if (btn) {
      btn.classList.toggle("on", !!on);
      btn.textContent = on ? "↩ В новые" : "✅ Просмотрено";
    }
    var badges = node.querySelector(".badges");
    var badge = badges ? badges.querySelector(".badge.seen") : null;
    if (on && badges && !badge) {
      badge = document.createElement("span");
      badge.className = "badge seen";
      badge.textContent = "✅ просмотрено";
      badges.appendChild(badge);
    } else if (!on && badge) {
      badge.parentNode.removeChild(badge);
    }
  }

  function markViewed(id, node) {
    if (!id || viewed[id]) return;
    viewed[id] = nowSec();
    LS.set("msk_viewed", viewed);
    setCardViewed(node, true);
    updateCounts();
  }

  function unmarkViewed(id, node) {
    if (!id || !viewed[id]) return;
    delete viewed[id];
    LS.set("msk_viewed", viewed);
    setCardViewed(node, false);
    updateCounts();
  }

  /* Карточка побыла в кадре DWELL мс — считаем просмотренной. Так «пролистал»
     отмечается сам, но мгновенный флинг мимо всего списка ничего не съест. */
  function observeCards() {
    if (io) { io.disconnect(); io = null; }
    if (typeof IntersectionObserver !== "function") return;
    io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        var node = en.target;
        if (en.isIntersecting) {
          if (node._seenTimer) return;
          node._seenTimer = setTimeout(function () {
            node._seenTimer = null;
            if (!document.documentElement.contains(node)) return;
            if (pointerBusy) return;   // палец на экране — не дёргаем карточку
            markViewed(node.getAttribute("data-card"), node);
          }, DWELL);
        } else if (node._seenTimer) {
          clearTimeout(node._seenTimer);
          node._seenTimer = null;
        }
      });
    }, { threshold: 0.15 });
    var cards = el.list.querySelectorAll(".card[data-card]");
    Array.prototype.forEach.call(cards, function (c) {
      if (!c.classList.contains("is-viewed")) io.observe(c);
    });
  }

  /* --- отрисовка ---
     mode: "rebuild" — пересобрать список (меню, фильтры, сортировка, старт);
           "keep"    — дорисовать/поправить, ничего не сдвигая. */
  function render(mode) {
    if (mode === "rebuild") {
      pinned = {};
      state.page = 1;
    }
    var items = visibleItems();
    var shown = items.slice(0, state.page * PER);
    shown.forEach(function (it) { pinned[it.id] = 1; });

    var blockedCount = Object.keys(blocked).length;
    var old = document.getElementById("unblock-chip");
    if (old) old.parentNode.removeChild(old);
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
        render("rebuild");
      });
      el.chips.appendChild(b);
    }

    setEmpty(items.length);
    el.list.innerHTML = "";
    shown.forEach(function (it) {
      el.list.appendChild(card(it));
    });

    var left = items.length - shown.length;
    el.more.hidden = left <= 0;
    if (left > 0) {
      el.more.textContent = "Показать ещё " + Math.min(PER, left) +
                            " · осталось " + left;
    }

    updateCounts();
    observeCards();
    updateHead();
    if (mode === "rebuild") window.scrollTo(0, 0);
  }

  function setEmpty(count) {
    el.empty.hidden = count > 0;
    if (count > 0) return;
    var narrowed = !!state.q.trim() || state.filters.unofficial ||
                   state.filters.fav || state.salaryMin > 0;
    if (narrowed) {
      el.emptyIcon.textContent = "🔍";
      el.emptyTitle.textContent = "Ничего не нашлось";
      el.emptyText.textContent = "Попробуйте изменить поиск или фильтры.";
    } else if (state.tab === "new") {
      el.emptyIcon.textContent = "🎉";
      el.emptyTitle.textContent = "Новых нет";
      el.emptyText.textContent = "Всё, что приезжало, вы уже пролистали. " +
        "Заглядывайте — новые вакансии приедут сами.";
    } else {
      el.emptyIcon.textContent = "📚";
      el.emptyTitle.textContent = "Пока пусто";
      el.emptyText.textContent = "Здесь появятся вакансии, которые вы " +
        "пролистали. Новые — в меню «✨ Новые».";
    }
  }

  function card(it) {
    var wrap = document.createElement("article");
    var seen = isViewed(it);
    wrap.className = "card" + (seen ? " is-viewed" : "");
    wrap.setAttribute("data-card", esc(it.id));

    var score = it.score || 0;
    var cls = score >= 70 ? "hi" : (score >= 45 ? "mid" : "lo");

    var badges = [];
    if (it.unofficial) badges.push('<span class="badge hot">🔥 без оформления</span>');
    if (seen) badges.push('<span class="badge seen">✅ просмотрено</span>');

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
    /* Просмотренную карточку прогон продолжает обновлять — так и говорим,
       чтобы не путалось с «добавил заново». */
    var upd = "";
    if (seen && it.last_seen && it.first_seen && it.last_seen > it.first_seen) {
      upd = "🔄 обновлено " + esc(ago(it.last_seen));
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
      '<div class="badges">' + badges.join("") + "</div>" +
      (it.employer ? '<div class="emp">🏢 ' + esc(it.employer) +
        (rating ? " · " + rating : "") + "</div>" : "") +
      (it.metro || it.address
        ? '<div class="addr">📍 ' + esc(it.metro || it.address) + "</div>"
        : "") +
      ((when || upd)
        ? '<div class="fresh">' + (when ? "<span>" + when + "</span>" : "") +
          (upd ? '<span class="upd">' + upd + "</span>" : "") + "</div>"
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
        '<button class="act seen-act' + (seen ? " on" : "") + '" data-seen="' +
          esc(it.id) + '">' +
          (seen ? "↩ В новые" : "✅ Просмотрено") +
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
    if (!t) return;

    // «Открыть на Авито» — значит, посмотрели
    if (t.tagName === "A" && t.classList.contains("open")) {
      var anode = cardOf(t);
      markViewed(anode ? anode.getAttribute("data-card") : "", anode);
      return;
    }
    if (t.tagName !== "BUTTON") return;

    if (t.hasAttribute("data-seen")) {
      var sid = t.getAttribute("data-seen");
      var snode = cardOf(t);
      if (viewed[sid]) unmarkViewed(sid, snode);
      else markViewed(sid, snode);
      return;   // список не пересобираем: карточка остаётся на месте
    }
    if (t.hasAttribute("data-block")) {
      var key = t.getAttribute("data-block");
      var label = t.getAttribute("data-block-label") || "работодателя";
      if (confirm("Заблокировать «" + label + "»?\n\nВсе вакансии от него " +
                  "исчезнут из списка — и текущие, и будущие.\n" +
                  "Вернуть можно кнопкой «Разблокировать» сверху.")) {
        blocked[key] = label;
        LS.set("msk_blocked", blocked);
        render("rebuild");
      }
      return;
    }
    var id = t.getAttribute("data-fav") || t.getAttribute("data-hide") ||
             t.getAttribute("data-note") || t.getAttribute("data-more");
    if (!id) return;

    /* Разобрались с карточкой (открыли описание, взяли в избранное,
       оставили заметку) — значит, увидели её. */
    if (t.hasAttribute("data-more") || t.hasAttribute("data-fav") ||
        t.hasAttribute("data-note")) {
      markViewed(id, cardOf(t));
    }

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

  el.tabs.addEventListener("click", function (ev) {
    var b = ev.target;
    while (b && b !== el.tabs && (!b.getAttribute ||
           !b.getAttribute("data-tab"))) b = b.parentNode;
    if (!b || b === el.tabs) return;
    var tab = b.getAttribute("data-tab");
    if (tab === state.tab) return;
    state.tab = tab;
    state.sort = TAB_SORT[tab] || "score";
    setSortUI();
    Array.prototype.forEach.call(el.tabs.children, function (c) {
      c.classList.toggle("on", c === b);
    });
    render("rebuild");
  });

  el.seg.addEventListener("click", function (ev) {
    var b = ev.target;
    if (b.tagName !== "BUTTON") return;
    state.sort = b.getAttribute("data-sort");
    setSortUI();
    render("rebuild");
  });

  el.chips.addEventListener("click", function (ev) {
    var b = ev.target;
    if (b.tagName !== "BUTTON" || !b.hasAttribute("data-filter")) return;
    var key = b.getAttribute("data-filter");
    state.filters[key] = !state.filters[key];
    b.classList.toggle("on", state.filters[key]);
    render("rebuild");
  });

  el.more.addEventListener("click", function () {
    state.page += 1;
    var y = window.scrollY;
    render("keep");
    window.scrollTo(0, y);
  });

  el.newBtn.addEventListener("click", function () {
    if (state.tab !== "new") {
      state.tab = "new";
      state.sort = TAB_SORT["new"];
      setSortUI();
      Array.prototype.forEach.call(el.tabs.children, function (c) {
        c.classList.toggle("on", c.getAttribute("data-tab") === "new");
      });
    }
    render("rebuild");
  });

  el.salary.addEventListener("change", function () {
    state.salaryMin = parseInt(el.salary.value, 10) || 0;
    render("rebuild");
  });

  var searchTimer = null;
  el.search.addEventListener("input", function () {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(function () {
      state.q = el.search.value;
      render("rebuild");
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

  /* 🔄 — «обновление списка»: подтянуть данные и пересобрать меню заново
     (просмотренное уезжает в «Просмотренные»). */
  el.refreshBtn.addEventListener("click", function () {
    el.refreshBtn.textContent = "⏳";
    render("rebuild");
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
  setSortUI();
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
