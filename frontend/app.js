const content = document.querySelector('#content');
const errorBox = document.querySelector('#error');
const paths = {
  document: '<path d="M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8Z"/><path d="M14 3v5h5M8 12h8M8 16h6"/>',
  search: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',
  calendar: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M7 3v4M17 3v4M3 11h18"/>',
  arrow: '<path d="M5 12h14m-5-5 5 5-5 5"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  sliders: '<path d="M3 6h5m4 0h9M3 18h9m4 0h5"/><circle cx="10" cy="6" r="2"/><circle cx="14" cy="18" r="2"/>',
  bulb: '<path d="M9 18h6M10 21h4M8 14a7 7 0 1 1 8 0c-1 1-1 2-1 4H9c0-2 0-3-1-4Z"/>',
  tag: '<path d="m3 3 9 1 9 9-8 8-9-9Z"/><circle cx="8" cy="8" r="1"/>',
};
function icon(name) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('aria-hidden', 'true');
  svg.classList.add('icon');
  svg.innerHTML = paths[name] || paths.document;
  return svg;
}
function element(tag, text, parent = content, className = '') {
  const el = document.createElement(tag);
  el.textContent = text;
  if (className) el.className = className;
  parent.append(el);
  return el;
}
function link(text, href, parent = content, className = '') {
  const el = element('a', text, parent, className);
  el.href = href;
  return el;
}
function showError(error) {
  errorBox.textContent = error.message;
  errorBox.hidden = false;
  errorBox.scrollIntoView({block: 'nearest'});
}
async function api(path = '', options = {}) {
  const response = await fetch(`/api/projects${path}`, options);
  if (!response.ok) {
    const body = await response.json();
    throw new Error(Array.isArray(body.detail)
      ? body.detail.map(e => `${e.loc.slice(1).join('.')}: ${e.msg}`).join('; ')
      : body.detail || 'Request failed');
  }
  return response.status === 204 ? null : response.json();
}
function heading(title, description) {
  const header = element('header', '', content, 'page-heading');
  element('h1', title, header);
  element('p', description, header, 'muted');
}
function sectionHeading(parent, title, symbol = 'document') {
  const header = element('div', '', parent, 'panel-heading');
  header.append(icon(symbol));
  element('h2', title, header);
  return header;
}
function panel(parent, title, symbol, className = '') {
  const box = element('section', '', parent, `panel ${className}`);
  sectionHeading(box, title, symbol);
  return box;
}
function tabs(text, count) {
  const row = element('div', '', content, 'section-tabs');
  const label = element('span', text, row, 'selected-tab');
  if (count !== undefined) element('span', String(count), label, 'count');
}
function date(value) {
  return new Date(value).toLocaleDateString(undefined, {month: 'short', day: 'numeric', year: 'numeric'});
}
function yearRange(project) {
  if (!project.yearFrom && !project.yearTo) return 'Any year';
  if (!project.yearFrom) return `Until ${project.yearTo}`;
  if (!project.yearTo) return `From ${project.yearFrom}`;
  return `${project.yearFrom} – ${project.yearTo}`;
}
function stat(parent, symbol, value, label) {
  const item = element('div', '', parent, 'stat');
  item.append(icon(symbol));
  const text = element('div', '', item);
  element('strong', String(value), text);
  element('span', label, text);
}
function note(parent, title, description) {
  const box = panel(parent, title, 'bulb', 'insight');
  element('p', description, box, 'muted');
}
function projectForm(project = {}) {
  const editing = Boolean(project.id);
  heading(editing ? 'Edit your research project' : 'Every discovery starts with a question',
    editing ? 'Refine your question and update your research preferences.'
      : 'Capture a research topic and give your next exploration a place to grow.');
  tabs(editing ? 'Project details' : 'New project');
  const layout = element('div', '', content, 'workspace');
  const f = element('form', '', layout, 'panel project-form');
  sectionHeading(f, 'Research project');
  f.innerHTML += `
    <label for="title">Project title</label>
    <input id="title" name="title" required maxlength="200" placeholder="Give your project a name">
    <label for="researchQuestion">Research question or topic</label>
    <textarea id="researchQuestion" name="researchQuestion" required maxlength="5000" placeholder="What would you like to explore?"></textarea>
    <label for="keywords">Keywords <span class="optional">Optional</span></label>
    <textarea id="keywords" name="keywords" class="keywords-input" aria-describedby="keyword-help" placeholder="e.g. large language models"></textarea>
    <p id="keyword-help" class="field-help">One keyword or phrase per line.</p>
    <div class="form-divider"></div>
    <h3>Research preferences</h3>
    <div class="field-row">
      <div><label for="yearFrom">From year <span class="optional">Optional</span></label><input id="yearFrom" name="yearFrom" type="number" min="1" max="9999" placeholder="Any"></div>
      <div><label for="yearTo">To year <span class="optional">Optional</span></label><input id="yearTo" name="yearTo" type="number" min="1" max="9999" placeholder="Any"></div>
      <div><label for="maxPaperCount">Paper limit <span class="optional">Optional</span></label><input id="maxPaperCount" name="maxPaperCount" type="number" min="1" max="1000" placeholder="Not set"></div>
    </div>
    <div class="form-actions"><button type="submit">Save project</button></div>`;
  for (const name of ['title', 'researchQuestion', 'yearFrom', 'yearTo', 'maxPaperCount']) {
    f.elements[name].value = project[name] ?? '';
  }
  f.elements.keywords.value = (project.keywords || []).join('\n');
  link('Cancel', editing ? `/projects/${project.id}` : '/', f.querySelector('.form-actions'), 'button secondary');
  const aside = element('aside', '', layout, 'context-column');
  note(aside, 'Start with curiosity', 'A focused question gives your research direction. Try describing what you want to understand, compare, or investigate.');
  const help = panel(aside, 'Make it your own', 'sliders');
  element('p', 'Add keywords to capture important concepts, and a year range to define the period you’re interested in.', help, 'muted');
  element('p', 'You can come back and edit these details at any time.', help, 'muted');
  f.addEventListener('submit', async event => {
    event.preventDefault();
    errorBox.hidden = true;
    const data = {
      title: f.elements.title.value,
      researchQuestion: f.elements.researchQuestion.value,
      keywords: f.elements.keywords.value.split('\n').map(s => s.trim()).filter(Boolean),
    };
    for (const name of ['yearFrom', 'yearTo', 'maxPaperCount']) {
      data[name] = f.elements[name].value === '' ? null : Number(f.elements[name].value);
    }
    const button = f.querySelector('button');
    button.disabled = true;
    button.textContent = 'Saving…';
    try {
      const saved = await api(editing ? `/${project.id}` : '', {
        method: editing ? 'PUT' : 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(data),
      });
      location.href = `/projects/${saved.id}`;
    } catch (error) {
      showError(error);
      button.disabled = false;
      button.textContent = 'Save project';
    }
  });
}
function dashboard(projects) {
  heading('A home for your next research discovery',
    'Capture your questions, organize your projects, and pick up where you left off.');
  const toolbar = element('div', '', content, 'search-toolbar');
  const searchBox = element('div', '', toolbar, 'search-box');
  searchBox.append(icon('search'));
  const search = element('input', '', searchBox);
  search.type = 'search';
  search.placeholder = 'Find a project in your library';
  search.setAttribute('aria-label', 'Find a project in your library');
  const create = link('New project', '/projects/new', toolbar, 'button');
  create.prepend(icon('plus'));
  const filters = element('div', '', content, 'filter-row');
  element('span', 'Your personal research library', filters, 'chip');
  element('span', 'Recently updated first', filters, 'sort-label');
  tabs('All projects', projects.length);
  const layout = element('div', '', content, 'workspace');
  const list = panel(layout, 'Saved projects');
  const results = element('div', '', list);
  const aside = element('aside', '', layout, 'context-column');
  const overview = panel(aside, 'Library overview', 'document');
  const stats = element('div', '', overview, 'library-stats');
  stat(stats, 'document', projects.length, projects.length === 1 ? 'saved project' : 'saved projects');
  stat(stats, 'tag', new Set(projects.flatMap(p => p.keywords.map(k => k.toLowerCase()))).size, 'unique keywords');
  note(aside, 'Room for your next idea', 'Keep a question close, give it a project, and return whenever inspiration strikes. Your research starts here.');
  function draw() {
    results.replaceChildren();
    const query = search.value.trim().toLowerCase();
    const filtered = projects.filter(p => [p.title, p.researchQuestion, ...p.keywords].join(' ').toLowerCase().includes(query));
    if (!filtered.length) {
      const empty = element('div', '', results, 'empty-state');
      empty.append(icon('document'));
      element('h3', projects.length ? 'No matching projects' : 'Your next discovery starts here', empty);
      element('p', projects.length ? 'Try a different title, topic, or keyword.' : 'Create your first project to save a question you want to explore.', empty, 'muted');
      if (!projects.length) link('Create a project', '/projects/new', empty, 'button');
    }
    for (const project of filtered) {
      const card = element('article', '', results, 'project-row');
      const title = element('h3', '', card);
      link(project.title, `/projects/${project.id}`, title);
      element('p', project.researchQuestion, card, 'project-question');
      const keywords = element('div', '', card, 'keyword-list');
      for (const keyword of project.keywords.slice(0, 4)) element('span', keyword, keywords, 'keyword');
      if (project.keywords.length > 4) element('span', `+${project.keywords.length - 4}`, keywords, 'keyword');
      const footer = element('div', '', card, 'project-meta');
      element('span', `Updated ${date(project.updatedAt)}`, footer);
      const open = link('Open project', `/projects/${project.id}`, footer, 'open-link');
      open.append(icon('arrow'));
    }
  }
  search.addEventListener('input', draw);
  draw();
}
function detail(project) {
  const breadcrumb = link('Library', '/', content, 'breadcrumb');
  breadcrumb.prepend(icon('arrow'));
  heading(project.title, 'Your research question, ideas, and preferences. All in one place.');
  const actions = element('div', '', content, 'detail-toolbar');
  element('span', 'Saved project', actions, 'chip saved-chip');
  link('Edit project', `/projects/${project.id}/edit`, actions, 'button').prepend(icon('sliders'));
  tabs('Overview');
  const layout = element('div', '', content, 'workspace');
  const left = element('div', '', layout, 'context-column');
  const summary = panel(left, 'Research topic summary');
  element('p', project.researchQuestion, summary, 'research-question');
  const stats = element('div', '', summary, 'stats');
  stat(stats, 'calendar', yearRange(project), 'publication years');
  stat(stats, 'document', project.maxPaperCount ?? 'Not set', 'paper limit');
  stat(stats, 'tag', project.keywords.length, 'keywords');
  const keywords = panel(left, 'Research keywords', 'tag');
  const keywordList = element('div', '', keywords, 'keyword-list detail-keywords');
  for (const keyword of project.keywords) element('span', keyword, keywordList, 'keyword');
  if (!project.keywords.length) element('p', 'No keywords added. Edit your project to add the concepts you want to explore.', keywordList, 'muted');
  const aside = element('aside', '', layout, 'context-column');
  const details = panel(aside, 'Project details', 'sliders');
  const dl = element('dl', '', details, 'details-list');
  for (const [label, value] of [['Created', date(project.createdAt)], ['Last updated', date(project.updatedAt)], ['Publication years', yearRange(project)], ['Maximum papers', project.maxPaperCount ?? 'Not specified']]) {
    element('dt', label, dl); element('dd', String(value), dl);
  }
  note(aside, 'Good research takes shape', 'Your project keeps the starting point of your research in focus. Revisit your question and refine it as your thinking develops.');
  const management = element('div', '', aside, 'project-management');
  const remove = element('button', 'Delete project', management, 'danger');
  literature(project, left, aside, actions, remove);
  remove.addEventListener('click', async () => {
    if (!confirm(`Delete “${project.title}”? This cannot be undone.`)) return;
    remove.disabled = true;
    try { await api(`/${project.id}`, {method: 'DELETE'}); location.href = '/'; }
    catch (error) { showError(error); remove.disabled = false; }
  });
}
function literature(project, left, aside, actions, remove) {
  const searchButton = element('button', 'Find papers', actions);
  searchButton.prepend(icon('search'));
  const papersPanel = panel(left, 'Papers', 'document');
  left.insertBefore(papersPanel, left.children[1]);
  const papersBody = element('div', '', papersPanel);
  const searchPanel = panel(aside, 'Literature search', 'search');
  aside.prepend(searchPanel);
  const searchBody = element('div', '', searchPanel);
  element('p', 'Loading saved papers…', papersBody, 'muted');
  let busy = false;
  let timer;
  let displayedRunId;
  const projectPath = `/${project.id}`;
  const editLink = actions.querySelector('a');
  editLink.classList.add('secondary');
  function setBusy(value) {
    busy = value;
    searchButton.disabled = value;
    searchButton.textContent = value ? 'Searching OpenAlex…' : 'Find papers';
    if (!value) searchButton.prepend(icon('search'));
    remove.disabled = value;
    editLink.setAttribute('aria-disabled', String(value));
  }
  editLink.addEventListener('click', event => { if (busy) event.preventDefault(); });
  function showPapers(papers, history) {
    papersBody.replaceChildren();
    papersPanel.querySelector('h2').textContent = `Papers (${papers.length})`;
    const completed = history.find(run => run.status === 'COMPLETED');
    if (completed) {
      const p = completed.parameters;
      const changed = p.query !== project.researchQuestion || p.yearFrom !== project.yearFrom
        || p.yearTo !== project.yearTo || p.maxPaperCount !== (project.maxPaperCount ?? 100);
      element('p', changed
        ? 'These results use earlier project details. Run a new search to update them.'
        : `Retrieved from ${completed.provider} on ${date(completed.finishedAt)}.`, papersBody, 'field-help');
      if (completed.skippedCount) element('p', `${completed.skippedCount} provider records could not be normalized.`, papersBody, 'field-help');
    }
    if (!papers.length) {
      const empty = element('div', '', papersBody, 'empty-state');
      empty.append(icon('search'));
      element('h3', completed ? 'No papers matched this search' : 'Explore the literature', empty);
      element('p', completed ? 'Try a shorter research topic or a wider year range.'
        : 'Find real scholarly papers from OpenAlex using your research question.', empty, 'muted');
      return;
    }
    for (const paper of papers) {
      const row = element('article', '', papersBody, 'project-row paper-row');
      element('h3', paper.title || 'Title unavailable', row);
      const authors = paper.authors.map(author => author.name).filter(Boolean);
      const authorLabel = authors.length ? authors.slice(0, 3).join(', ') + (authors.length > 3 ? ' et al.' : '') : 'Authors unavailable';
      element('p', `${authorLabel} · ${paper.publicationYear ?? 'Year unavailable'}`, row, 'paper-metadata');
      if (paper.venue) element('p', paper.venue, row, 'paper-metadata');
      if (paper.doi) element('p', `DOI: ${paper.doi}`, row, 'paper-doi');
      const footer = element('div', '', row, 'project-meta');
      element('span', `Citations: ${paper.citationCount ?? 'Unavailable'} · ${paper.source}`, footer);
      const source = link('View source', paper.sourceUrl, footer, 'open-link');
      source.target = '_blank';
      source.rel = 'noopener noreferrer';
      source.append(icon('arrow'));
    }
  }
  function showSearch(history) {
    searchBody.replaceChildren();
    const latest = history[0];
    setBusy(latest?.status === 'SEARCHING');
    element('p', 'OpenAlex searches your research question with the saved year range. Keywords remain project notes.', searchBody, 'field-help');
    element('span', 'Search query', searchBody, 'query-label');
    element('p', latest?.parameters.query ?? project.researchQuestion, searchBody, 'search-query');
    if (!latest) {
      element('p', 'No search has been run yet.', searchBody, 'muted');
      return;
    }
    element('p', busy ? 'Searching scholarly papers…'
      : latest.status === 'FAILED' ? latest.errorMessage
      : `${latest.paperCount} papers saved · ${latest.totalFound.toLocaleString()} matches in OpenAlex`,
      searchBody, latest.status === 'FAILED' ? 'search-failure' : 'search-status');
    if (latest.status === 'FAILED' && history.some(run => run.status === 'COMPLETED')) {
      element('p', 'Results from your last successful search are still available.', searchBody, 'field-help');
    }
    const recent = element('details', '', searchBody, 'search-history');
    element('summary', 'Recent searches', recent);
    for (const run of history.slice(0, 5)) {
      const item = element('div', '', recent, 'search-history-item');
      element('strong', `${date(run.startedAt)} · ${run.status.toLowerCase()}`, item);
      element('p', run.parameters.query, item);
      element('small', `${yearRange(run.parameters)} · Limit ${run.parameters.maxPaperCount}`, item);
    }
  }
  async function refresh() {
    clearTimeout(timer);
    const history = await api(`${projectPath}/searches`);
    showSearch(history);
    const latestId = history[0]?.id ?? null;
    if (!busy || displayedRunId === undefined) {
      const papers = await api(`${projectPath}/papers`);
      showPapers(papers, history);
      displayedRunId = latestId;
    }
    if (busy) timer = setTimeout(() => refresh().catch(showError), 2000);
  }
  searchButton.addEventListener('click', async () => {
    clearTimeout(timer);
    setBusy(true);
    errorBox.hidden = true;
    searchBody.replaceChildren();
    element('p', 'Searching OpenAlex. This can take up to a minute…', searchBody, 'search-status');
    try {
      await api(`${projectPath}/search`, {method: 'POST'});
    } catch (error) { showError(error); }
    finally {
      setBusy(false);
      try { await refresh(); } catch (error) { showError(error); }
    }
  });
  refresh().catch(error => {
    papersBody.replaceChildren();
    element('p', 'Unable to load saved papers. Refresh to try again.', papersBody, 'muted');
    showError(error);
  });
}
async function render() {
  const parts = location.pathname.split('/').filter(Boolean);
  const currentNav = document.querySelector(`[data-nav="${parts[1] === 'new' ? 'new' : 'library'}"]`);
  currentNav.setAttribute('aria-current', 'page');
  if (!parts.length) {
    const projects = await api();
    content.replaceChildren();
    dashboard(projects);
  } else if (parts[1] === 'new') {
    content.replaceChildren();
    projectForm();
  } else {
    const project = await api(`/${parts[1]}`);
    content.replaceChildren();
    document.title = `${project.title} · ResearchPilot`;
    if (parts[2] === 'edit') projectForm(project);
    else detail(project);
  }
}
render().catch(error => {
  content.replaceChildren();
  heading('Unable to load this page', 'Please try again or return to your library.');
  link('Back to library', '/', content, 'button');
  showError(error);
});
