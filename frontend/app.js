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
const SEARCH_STAGES = {
  RETRIEVING: 'Searching scholarly databases…',
  ANALYZING: 'Removing duplicates…',
  EMBEDDING: 'Embedding papers and scoring relevance…',
  CLUSTERING: 'Discovering research themes…',
  NAMING: 'Naming the clusters…',
};
const ACCESS_LABEL = {
  OPEN_ACCESS: 'A free full-text copy is available.',
  ABSTRACT_ONLY: 'Only the abstract is available.',
  UNKNOWN: 'Full-text availability is unknown.',
};
function accessBadge(status) {
  const span = document.createElement('span');
  span.className = `access-pill access-${(status || 'UNKNOWN').toLowerCase()}`;
  span.textContent = {OPEN_ACCESS: 'Open access', ABSTRACT_ONLY: 'Abstract only'}[status] || 'Unknown';
  return span;
}
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
    const error = new Error(Array.isArray(body.detail)
      ? body.detail.map(e => `${e.loc.slice(1).join('.')}: ${e.msg}`).join('; ')
      : body.detail || 'Request failed');
    error.code = body.code;
    error.status = response.status;
    throw error;
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
function sortedPapers(papers, order) {
  const result = [...papers];
  if (order === 'relevance') return result;
  const relevance = (a, b) => (b.relevanceScore ?? -1) - (a.relevanceScore ?? -1);
  const knownFirst = (a, b) => a == null ? (b == null ? 0 : 1) : (b == null ? -1 : 0);
  return result.sort((a, b) => {
    if (order === 'citations') {
      const missing = knownFirst(a.citationCount, b.citationCount);
      return missing || (b.citationCount - a.citationCount) || relevance(a, b);
    }
    if (order === 'newest' || order === 'oldest') {
      const first = a.publicationDate || (a.publicationYear && String(a.publicationYear));
      const second = b.publicationDate || (b.publicationYear && String(b.publicationYear));
      const missing = knownFirst(first, second);
      const dateOrder = first && second ? first.localeCompare(second) : 0;
      return missing || (order === 'newest' ? -dateOrder : dateOrder) || relevance(a, b);
    }
    const missing = knownFirst(a.title, b.title);
    return missing || (a.title && b.title ? a.title.localeCompare(b.title, undefined, {sensitivity: 'base'}) : 0)
      || relevance(a, b);
  });
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
  heading(editing ? 'Edit your research project' : 'Start a reference library',
    editing ? 'Update your library and optional discovery settings.'
      : 'Name your project, then add the references you need.');
  tabs(editing ? 'Project details' : 'New project');
  const layout = element('div', '', content, 'workspace');
  const f = element('form', '', layout, 'panel project-form');
  sectionHeading(f, 'Research project');
  f.innerHTML += `
    <label for="title">Project title</label>
    <input id="title" name="title" required maxlength="200" placeholder="Give your project a name">
    <details class="project-discovery-settings">
      <summary>Discover papers settings (optional)</summary>
      <label for="researchQuestion">Research description</label>
      <textarea id="researchQuestion" name="researchQuestion" maxlength="5000" aria-describedby="description-help" placeholder="Describe what you want to understand…"></textarea>
      <p id="description-help" class="field-help">Required only to discover papers. It guides query suggestions, relevance, and subtopic names.</p>
      <label for="keywords">Keywords <span class="optional">Optional</span></label>
      <textarea id="keywords" name="keywords" class="keywords-input" aria-describedby="keyword-help" placeholder="e.g. large language models"></textarea>
      <p id="keyword-help" class="field-help">One keyword or phrase per line.</p>
      <div class="field-row">
        <div><label for="yearFrom">From year <span class="optional">Optional</span></label><input id="yearFrom" name="yearFrom" type="number" min="1" max="9999" placeholder="Any"></div>
        <div><label for="yearTo">To year <span class="optional">Optional</span></label><input id="yearTo" name="yearTo" type="number" min="1" max="9999" placeholder="Any"></div>
        <div><label for="maxPaperCount">Paper limit <span class="optional">Optional</span></label><input id="maxPaperCount" name="maxPaperCount" type="number" min="1" max="1000" placeholder="Not set"></div>
      </div>
    </details>
    <div class="form-actions"><button type="submit">Save project</button></div>`;
  for (const name of ['title', 'researchQuestion', 'yearFrom', 'yearTo', 'maxPaperCount']) {
    f.elements[name].value = project[name] ?? '';
  }
  f.elements.keywords.value = (project.keywords || []).join('\n');
  if (project.researchQuestion || project.keywords?.length || project.yearFrom || project.yearTo || project.maxPaperCount) {
    f.querySelector('.project-discovery-settings').open = true;
  }
  link('Cancel', editing ? `/projects/${project.id}` : '/', f.querySelector('.form-actions'), 'button secondary');
  const aside = element('aside', '', layout, 'context-column');
  note(aside, 'Build your library', 'Add citations, links, notes, and reading progress as you work. You can start with just a project title.');
  const help = panel(aside, 'Discover papers later', 'sliders');
  element('p', 'Add a research description whenever you want to search scholarly sources for more papers.', help, 'muted');
  f.addEventListener('submit', async event => {
    event.preventDefault();
    errorBox.hidden = true;
    const data = {
      title: f.elements.title.value,
      researchQuestion: f.elements.researchQuestion.value.trim() || null,
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
async function settings() {
  const response = await fetch('/api/settings/status');
  if (!response.ok) throw new Error('Unable to load provider settings.');
  const status = await response.json();
  heading('Settings', 'See which services are configured and how to set them up.');
  tabs('Provider settings');
  const layout = element('div', '', content, 'settings-layout');
  const services = element('div', '', layout, 'settings-services');
  const source = panel(services, 'Scholarly papers', 'search', 'settings-panel');
  const active = element('div', '', source, 'settings-active-source');
  const sourceNames = status.scholarlyProviders || [status.scholarlyProvider];
  const activeIds = sourceNames.map((name) => name.toLowerCase());
  const sourceLabel = (name) => ({scopus: 'Scopus', openalex: 'OpenAlex'})[name.toLowerCase()] || name;
  const several = sourceNames.length > 1;
  element('span', several ? 'CURRENT SOURCES' : 'CURRENT SOURCE', active, 'settings-eyebrow');
  element('strong', sourceNames.map(sourceLabel).join(' + '), active, 'settings-active-name');
  element('p', several
    ? 'Paper titles, authors, citation counts, and links come from these sources; duplicates are merged.'
    : 'Paper titles, authors, citation counts, and links come from this source.', active);
  const sourceList = element('div', '', source, 'settings-service-list');
  const serviceRow = (parent, name, description, badge, tone) => {
    const row = element('div', '', parent, 'settings-service-row');
    const text = element('div', '', row);
    element('h3', name, text);
    element('p', description, text);
    element('span', badge, row, `settings-status ${tone}`);
  };
  serviceRow(sourceList, 'OpenAlex',
    status.openAlexApiKeyConfigured
      ? `API key configured · ${status.openAlexEmailConfigured ? 'email configured' : 'email optional'}`
      : `No API key needed · ${status.openAlexEmailConfigured ? 'email configured' : 'email optional'}`,
    activeIds.includes('openalex') ? 'In use' : 'Available',
    activeIds.includes('openalex') ? 'settings-status-active' : 'settings-status-neutral');
  serviceRow(sourceList, 'Scopus',
    status.elsevierApiKeyConfigured ? 'Elsevier API key configured' : 'Requires an Elsevier API key',
    activeIds.includes('scopus') ? 'In use'
      : status.elsevierApiKeyConfigured ? 'Configured' : 'Not configured',
    activeIds.includes('scopus') ? 'settings-status-active'
      : status.elsevierApiKeyConfigured ? 'settings-status-neutral' : 'settings-status-missing');

  const ai = panel(services, 'Research assistance', 'bulb', 'settings-panel');
  element('p', 'OpenAI supports query suggestions, relevance scoring, clustering, names, and paper explanations.', ai, 'settings-panel-intro');
  const aiList = element('div', '', ai, 'settings-service-list');
  serviceRow(aiList, status.llmProvider,
    status.openAiApiKeyConfigured ? 'OPENAI_API_KEY is set' : 'Set OPENAI_API_KEY to use AI-assisted search',
    status.openAiApiKeyConfigured ? 'Configured' : 'Needs setup',
    status.openAiApiKeyConfigured ? 'settings-status-active' : 'settings-status-missing');
  serviceRow(aiList, 'API endpoint',
    status.customOpenAiEndpointConfigured ? 'Using a custom OpenAI-compatible endpoint' : 'Using the default OpenAI endpoint',
    status.customOpenAiEndpointConfigured ? 'Custom' : 'Default', 'settings-status-neutral');

  const help = panel(layout, 'How to configure', 'sliders', 'settings-panel settings-help');
  element('p', 'Change these settings in the server’s .env file, then restart ResearchPilot.', help, 'settings-panel-intro');
  const steps = element('ol', '', help, 'settings-steps');
  const openAiStep = element('li', '', steps);
  element('strong', 'Enable research assistance', openAiStep);
  const openAiText = element('p', '', openAiStep);
  element('span', 'Set ', openAiText);
  element('code', 'OPENAI_API_KEY', openAiText);
  element('span', '. An optional ', openAiText);
  element('code', 'OPENAI_BASE_URL', openAiText);
  element('span', ' selects a compatible endpoint.', openAiText);
  const sourceStep = element('li', '', steps);
  element('strong', 'Choose a paper source', sourceStep);
  const sourceText = element('p', '', sourceStep);
  element('span', 'Set ', sourceText);
  element('code', 'SCHOLARLY_PROVIDER', sourceText);
  element('span', ' to openalex or scopus. Scopus also needs ', sourceText);
  element('code', 'ELSEVIER_API_KEY', sourceText);
  element('span', '.', sourceText);
  const optionalStep = element('li', '', steps);
  element('strong', 'Optional OpenAlex details', optionalStep);
  const optionalText = element('p', '', optionalStep);
  element('span', 'Add ', optionalText);
  element('code', 'OPENALEX_API_KEY', optionalText);
  element('span', ' or ', optionalText);
  element('code', 'OPENALEX_EMAIL', optionalText);
  element('span', ' if you use them.', optionalText);
  element('p', 'Scopus access can also depend on institutional entitlement and network or VPN access.', help, 'settings-note');
  element('p', 'Statuses show configuration only; they do not test a live connection. API keys are never sent to the browser.', help, 'settings-note');
  link('Back to library', '/', help, 'button secondary settings-back');
}
function dashboard(projects) {
  heading('Your projects', 'Open a reference library or start a new one.');
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
  element('span', `${projects.length} ${projects.length === 1 ? 'project' : 'projects'} · ${new Set(projects.flatMap(p => p.keywords.map(k => k.toLowerCase()))).size} unique keywords`, filters, 'library-summary');
  element('span', 'Recently updated first', filters, 'sort-label');
  const list = panel(content, 'Saved projects', 'document', 'library-panel');
  const results = element('div', '', list);
  function draw() {
    results.replaceChildren();
    const query = search.value.trim().toLowerCase();
    const filtered = projects.filter(p => [p.title, p.researchQuestion, ...p.keywords].join(' ').toLowerCase().includes(query));
    if (!filtered.length) {
      const empty = element('div', '', results, 'empty-state');
      empty.append(icon('document'));
      element('h3', projects.length ? 'No matching projects' : 'Your reference library starts here', empty);
      element('p', projects.length ? 'Try a different title, topic, or keyword.' : 'Create a project to collect references.', empty, 'muted');
      if (!projects.length) link('Create a project', '/projects/new', empty, 'button');
    }
    for (const project of filtered) {
      const card = element('article', '', results, 'project-row');
      const title = element('h3', '', card);
      link(project.title, `/projects/${project.id}`, title);
      if (project.researchQuestion) element('p', project.researchQuestion, card, 'project-question');
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
  heading(project.title, 'Collect and manage the references for this project.');
  const actions = element('div', '', content, 'detail-toolbar');
  element('span', 'Saved project', actions, 'chip saved-chip');
  link('Edit project', `/projects/${project.id}/edit`, actions, 'button').prepend(icon('sliders'));
  const pageTabs = element('div', '', content, 'section-tabs project-tabs');
  const referencesTab = element('button', 'References', pageTabs, 'selected-tab');
  const discoveryTab = element('button', 'Discover papers', pageTabs);
  referencesTab.type = discoveryTab.type = 'button';
  const layout = element('div', '', content, 'project-workspace');
  layout.hidden = true;
  const referencesPanel = element('div', '', content);
  let discoveryLoaded = false;
  const summary = element('section', '', layout, 'project-summary');
  const facts = element('div', '', summary, 'project-facts');
  element('span', `${yearRange(project)} · ${project.maxPaperCount ?? 'Default'} paper limit`, facts);
  const keywordList = element('div', '', facts, 'keyword-list');
  for (const keyword of project.keywords) element('span', keyword, keywordList, 'keyword');
  const details = element('details', '', summary, 'project-details');
  element('summary', 'Project details', details);
  if (project.researchQuestion) {
    element('h2', 'Research description', details);
    element('p', project.researchQuestion, details, 'research-question');
  }
  const dl = element('dl', '', details, 'details-list');
  for (const [label, value] of [['Created', date(project.createdAt)], ['Last updated', date(project.updatedAt)]]) {
    element('dt', label, dl); element('dd', value, dl);
  }
  const remove = element('button', 'Delete project', actions, 'danger');
  const aside = element('div', '', layout, 'search-configuration');
  const left = element('div', '', layout, 'project-results');
  const referenceLibrary = renderReferenceLibrary(project, referencesPanel);
  function selectTab(references) {
    layout.hidden = references;
    referencesPanel.hidden = !references;
    referencesTab.classList.toggle('selected-tab', references);
    discoveryTab.classList.toggle('selected-tab', !references);
    const searchButton = actions.querySelector('.discovery-search-button');
    if (searchButton) searchButton.hidden = references || !project.researchQuestion;
    if (!references && !discoveryLoaded) {
      discoveryLoaded = true;
      if (!project.researchQuestion) {
        const setup = panel(left, 'Set up paper discovery', 'search');
        element('p', 'Add a research description to search scholarly sources for papers.', setup, 'muted');
        link('Edit project', `/projects/${project.id}/edit`, setup, 'button');
      }
      literature(project, left, aside, actions, remove, referenceLibrary);
    }
  }
  referencesTab.addEventListener('click', () => selectTab(true));
  discoveryTab.addEventListener('click', () => selectTab(false));
  remove.addEventListener('click', async () => {
    if (!confirm(`Delete “${project.title}”? This cannot be undone.`)) return;
    remove.disabled = true;
    try { await api(`/${project.id}`, {method: 'DELETE'}); location.href = '/'; }
    catch (error) { showError(error); remove.disabled = false; }
  });
}
function renderReferenceLibrary(project, container) {
  const projectPath = `/${project.id}/references`;
  const savedIds = new Set();
  const savedDois = new Set();
  const doiKey = doi => doi?.trim().toLowerCase().replace(/^(https?:\/\/doi\.org\/|doi:)/, '');
  const toolbar = element('div', '', container, 'reference-toolbar');
  element('h2', 'Reference library', toolbar);
  const addButton = element('button', 'Add reference', toolbar);
  const readingStatuses = [['TO_READ', 'To read'], ['READING', 'Reading'], ['READ', 'Read']];
  const filterLabel = element('label', 'Filter by reading status', toolbar, 'reference-reading-filter');
  const filter = element('select', '', filterLabel);
  filter.setAttribute('aria-label', 'Filter by reading status');
  for (const [value, label] of [['ALL', 'All'], ...readingStatuses]) element('option', label, filter).value = value;
  const citedLabel = element('label', 'Citation status', toolbar, 'reference-reading-filter');
  const citedFilter = element('select', '', citedLabel);
  citedFilter.setAttribute('aria-label', 'Filter by citation status');
  for (const [value, label] of [['ALL', 'All'], ['CITED', 'Cited'], ['NOT_CITED', 'Not cited']]) {
    element('option', label, citedFilter).value = value;
  }
  const searchLabel = element('label', 'Search library', toolbar, 'reference-library-search');
  const searchFilter = element('input', '', searchLabel);
  searchFilter.type = 'search'; searchFilter.placeholder = 'Title, author, venue, DOI, or notes';
  const yearLabel = element('label', 'Year', toolbar, 'reference-library-year');
  const yearFilter = element('input', '', yearLabel);
  yearFilter.type = 'number'; yearFilter.min = '1'; yearFilter.max = '9999'; yearFilter.placeholder = 'Any';
  const toolbarStatus = element('span', '', toolbar, 'reference-toolbar-status');
  toolbarStatus.setAttribute('role', 'status'); toolbarStatus.setAttribute('aria-live', 'polite');
  let references = [];
  const pendingStatuses = new Set();
  const citationMessages = new Map();
  // Notes drafts live only in page memory, keyed by reference ID, so rerenders keep them.
  const noteDrafts = new Map();
  const unsaved = draft => draft.state === 'saving' || draft.text !== draft.saved;
  window.addEventListener('beforeunload', event => {
    if ([...noteDrafts.values()].some(unsaved)) { event.preventDefault(); event.returnValue = ''; }
  });
  for (const control of [filter, citedFilter, searchFilter, yearFilter]) {
    control.addEventListener(control.tagName === 'SELECT' ? 'change' : 'input', render);
  }
  toolbar.append(addButton);
  const formBox = element('section', '', container, 'panel reference-form-box');
  formBox.hidden = true;
  const list = element('section', '', container, 'panel reference-list');
  let editing = null;
  let lookupVersion = 0;
  const form = element('form', '', formBox, 'reference-form');
  const fields = [
    ['title', 'Title', 'text'], ['authors', 'Authors (one per line)', 'textarea'],
    ['year', 'Year', 'number'], ['venue', 'Journal or venue', 'text'],
    ['doi', 'DOI', 'text'], ['url', 'Link', 'url'], ['notes', 'Notes', 'textarea'],
  ];
  let doiWrap;
  for (const [name, labelText, type] of fields) {
    const parent = name === 'doi' ? (doiWrap = element('div', '', form, 'reference-doi-field')) : form;
    const label = element('label', labelText, parent);
    const input = element(type === 'textarea' ? 'textarea' : 'input', '', label);
    input.name = name;
    if (type !== 'textarea') input.type = type;
    if (name === 'title') input.required = true;
    if (name === 'year') { input.min = '1'; input.max = '9999'; }
  }
  const lookupButton = element('button', 'Look up DOI', doiWrap, 'secondary');
  lookupButton.type = 'button';
  const lookupStatus = element('p', '', doiWrap, 'field-help reference-lookup-status');
  lookupStatus.setAttribute('role', 'status');
  const summaryButton = element('button', 'Write AI summary from abstract', doiWrap, 'secondary');
  summaryButton.type = 'button';
  summaryButton.hidden = true;
  const summaryStatus = element('p', '', doiWrap, 'field-help reference-lookup-status');
  summaryStatus.setAttribute('role', 'status');
  form.elements.doi.addEventListener('input', () => {
    ++lookupVersion;
    lookupButton.disabled = false;
    lookupButton.textContent = 'Look up DOI';
    lookupStatus.textContent = '';
    summaryButton.hidden = true;
    summaryStatus.textContent = '';
  });
  lookupButton.addEventListener('click', async () => {
    const doi = form.elements.doi.value.trim();
    if (!doi) { lookupStatus.textContent = 'Enter a DOI first.'; return; }
    const version = ++lookupVersion;
    lookupButton.disabled = true;
    lookupButton.textContent = 'Looking up…';
    lookupStatus.textContent = 'Looking up DOI metadata…';
    try {
      const draft = await api(`${projectPath}/lookup?doi=${encodeURIComponent(doi)}`);
      if (version !== lookupVersion || doi !== form.elements.doi.value.trim()) return;
      for (const name of ['title', 'year', 'venue', 'url', 'doi']) {
        if (draft[name] != null) form.elements[name].value = draft[name];
      }
      if (draft.authors.length) form.elements.authors.value = draft.authors.join('\n');
      status.value = 'Published';
      lookupStatus.textContent = `Filled from ${draft.source}. Review the details, then save.`;
      summaryButton.hidden = !draft.abstract || Boolean(editing);
      summaryStatus.textContent = '';
    } catch (error) {
      if (version === lookupVersion) lookupStatus.textContent = error.message;
    } finally {
      if (version === lookupVersion) {
        lookupButton.disabled = false;
        lookupButton.textContent = 'Look up DOI';
      }
    }
  });
  summaryButton.addEventListener('click', async () => {
    const doi = form.elements.doi.value.trim();
    const version = lookupVersion;
    summaryButton.disabled = true;
    summaryStatus.textContent = 'Writing summary from the provider abstract…';
    try {
      const result = await api(`${projectPath}/summary`, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({doi}),
      });
      if (version !== lookupVersion || doi !== form.elements.doi.value.trim()) return;
      const notes = form.elements.notes;
      notes.value = notes.value.trim() ? `${notes.value.trim()}\n\n${result.summary}` : result.summary;
      summaryStatus.textContent = 'AI summary added to Notes. Review and edit it before saving.';
    } catch (error) {
      if (version === lookupVersion) summaryStatus.textContent = error.message;
    } finally {
      if (version === lookupVersion) summaryButton.disabled = false;
    }
  });
  const statusLabel = element('label', 'Publication status', form);
  const status = element('select', '', statusLabel);
  status.name = 'status';
  status.setAttribute('aria-label', 'Publication status');
  for (const value of ['Draft', 'Submitted', 'Accepted', 'Published']) element('option', value, status).value = value;
  const buttons = element('div', '', form, 'form-actions');
  element('button', 'Save reference', buttons);
  element('button', 'Cancel', buttons, 'secondary').addEventListener('click', event => {
    event.preventDefault(); ++lookupVersion; formBox.hidden = true;
  });
  function openForm(reference = null) {
    ++lookupVersion;
    editing = reference;
    form.reset();
    lookupStatus.textContent = '';
    lookupButton.disabled = false;
    lookupButton.textContent = 'Look up DOI';
    summaryButton.hidden = true;
    summaryButton.disabled = false;
    summaryStatus.textContent = '';
    for (const [name] of fields) {
      form.elements[name].value = reference?.[name] ?? '';
    }
    form.elements.authors.value = (reference?.authors || []).join('\n');
    status.value = reference?.status || 'Draft';
    // Existing references edit notes only in the notes editor, so this form cannot overwrite them.
    form.elements.notes.closest('label').hidden = Boolean(reference);
    formBox.hidden = false;
    form.elements.title.focus();
  }
  addButton.addEventListener('click', () => openForm());
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const data = {
      title: form.elements.title.value.trim(),
      authors: form.elements.authors.value.split('\n').map(s => s.trim()).filter(Boolean),
      year: form.elements.year.value ? Number(form.elements.year.value) : null,
      venue: form.elements.venue.value.trim() || null,
      doi: form.elements.doi.value.trim() || null,
      url: form.elements.url.value.trim() || null,
      status: status.value,
    };
    if (!editing) data.notes = form.elements.notes.value;
    try {
      await api(editing ? `${projectPath}/${editing.id}` : projectPath, {
        method: editing ? 'PATCH' : 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(data),
      });
      ++lookupVersion;
      formBox.hidden = true;
      await refresh();
    } catch (error) { showError(error); }
  });
  // The initial load must not notify: the project page's own first refresh waits for it.
  async function refresh({notify = true} = {}) {
    references = await api(projectPath);
    for (const id of noteDrafts.keys()) {
      if (!references.some(reference => reference.id === id)) noteDrafts.delete(id);
    }
    savedIds.clear();
    savedDois.clear();
    references.forEach(reference => {
      if (reference.paperId) {
        savedIds.add(reference.paperId);
        if (reference.doi) savedDois.add(doiKey(reference.doi));
      }
    });
    render();
    if (notify) window.dispatchEvent(new Event('references-changed'));
  }
  function render() {
    const query = searchFilter.value.trim().toLocaleLowerCase();
    const selectedYear = yearFilter.value ? Number(yearFilter.value) : null;
    const visible = references.filter(reference => {
      const readingMatches = filter.value === 'ALL' || reference.readingStatus === filter.value;
      const citedMatches = citedFilter.value === 'ALL' ||
        (citedFilter.value === 'CITED' ? reference.isCited : !reference.isCited);
      const yearMatches = selectedYear === null || reference.year === selectedYear;
      const searchable = [reference.title, ...(reference.authors || []), reference.venue,
        reference.doi, reference.notes].filter(Boolean).join(' ').toLocaleLowerCase();
      return readingMatches && citedMatches && yearMatches && (!query || searchable.includes(query));
    });
    const active = document.activeElement;
    const focusedNote = active?.dataset?.noteFor && list.contains(active)
      ? {id: active.dataset.noteFor, start: active.selectionStart, end: active.selectionEnd} : null;
    list.replaceChildren();
    sectionHeading(list, `Saved references (${visible.length} of ${references.length})`);
    if (!references.length) element('p', 'No references yet. Save a search paper or add your own work.', list, 'muted');
    if (references.length && !visible.length) element('p', 'No references match these filters.', list, 'muted');
    for (const reference of visible) {
      const row = element('article', '', list, 'reference-row');
      element('h3', reference.title || 'Title unavailable', row);
      const metadata = [reference.authors.join(', '), reference.year, reference.venue, reference.status].filter(Boolean).join(' · ');
      if (metadata) element('p', metadata, row, 'paper-metadata');
      if (reference.doi) element('p', `DOI: ${reference.doi}`, row, 'paper-doi');
      if (noteDrafts.has(reference.id)) notesEditor(reference, row);
      else if (reference.notes) element('p', reference.notes, row, 'reference-notes');
      const citationControls = element('div', '', row, 'reference-citation-controls');
      const citedControl = element('label', '', citationControls, 'reference-cited-state');
      const citedCheckbox = element('input', '', citedControl);
      citedCheckbox.type = 'checkbox'; citedCheckbox.checked = reference.isCited;
      citedCheckbox.setAttribute('aria-label', 'Cited in paper');
      citedControl.append(document.createTextNode(' Cited in paper'));
      const citationStatus = element('span', '', citationControls, 'reference-save-status');
      citationStatus.setAttribute('role', 'status'); citationStatus.setAttribute('aria-live', 'polite');
      citationStatus.textContent = citationMessages.get(reference.id) || '';
      citedCheckbox.addEventListener('change', async () => {
        citedCheckbox.disabled = true; citationStatus.textContent = 'Saving…';
        try {
          const updated = await api(`${projectPath}/${reference.id}`, {
            method: 'PATCH', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({isCited: citedCheckbox.checked}),
          });
          references = references.map(item => item.id === updated.id ? updated : item);
          citationMessages.set(reference.id, 'Saved');
          render();
        } catch (error) {
          citedCheckbox.checked = reference.isCited; citedCheckbox.disabled = false;
          citationStatus.textContent = `Not saved: ${error.message}`;
        }
      });
      if (reference.isCited) {
        const numberLabel = element('label', 'Citation number (optional)', citationControls);
        const numberInput = element('input', '', numberLabel);
        numberInput.type = 'number'; numberInput.min = '1';
        numberInput.value = reference.citationNumber ?? '';
        const saveNumber = element('button', 'Save number', citationControls, 'secondary');
        saveNumber.type = 'button';
        saveNumber.addEventListener('click', async () => {
          saveNumber.disabled = true; citationStatus.textContent = 'Saving…';
          try {
            const updated = await api(`${projectPath}/${reference.id}`, {
              method: 'PATCH', headers: {'Content-Type': 'application/json'},
              body: JSON.stringify({citationNumber: numberInput.value ? Number(numberInput.value) : null}),
            });
            references = references.map(item => item.id === updated.id ? updated : item);
            citationMessages.set(reference.id, 'Saved');
            render();
          } catch (error) {
            saveNumber.disabled = false; citationStatus.textContent = `Not saved: ${error.message}`;
          }
        });
      } else if (reference.previousCitationNumber !== null) {
        element('span', `Previously cited as ${reference.previousCitationNumber}`, citationControls,
          'reference-citation-history');
        const restore = element('button', 'Restore number', citationControls, 'secondary');
        restore.type = 'button';
        restore.addEventListener('click', async () => {
          restore.disabled = true; citationStatus.textContent = 'Saving…';
          try {
            let updated = await api(`${projectPath}/${reference.id}`, {method: 'PATCH',
              headers: {'Content-Type': 'application/json'}, body: JSON.stringify({isCited: true})});
            references = references.map(item => item.id === updated.id ? updated : item);
            try {
              updated = await api(`${projectPath}/${reference.id}`, {method: 'PATCH',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({citationNumber: reference.previousCitationNumber})});
              references = references.map(item => item.id === updated.id ? updated : item);
              citationMessages.set(reference.id, 'Saved');
              render();
            } catch (error) {
              citationMessages.set(reference.id, `Number not restored: ${error.message}`);
              render();
            }
          } catch (error) {
            restore.disabled = false; citationStatus.textContent = `Not saved: ${error.message}`;
          }
        });
      }
      const readingLabel = element('label', 'Reading status', row, 'reference-reading-status');
      const readingSelect = element('select', '', readingLabel);
      readingSelect.setAttribute('aria-label', 'Reading status');
      for (const [value, label] of readingStatuses) element('option', label, readingSelect).value = value;
      readingSelect.value = reference.readingStatus;
      readingSelect.disabled = pendingStatuses.has(reference.id);
      readingSelect.addEventListener('change', async () => {
        pendingStatuses.add(reference.id);
        readingSelect.disabled = true;
        try {
          const updated = await api(`${projectPath}/${reference.id}`, {
            method: 'PATCH', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({readingStatus: readingSelect.value}),
          });
          references = references.map(item => item.id === updated.id ? updated : item);
        } catch (error) {
          showError(error);
        } finally {
          pendingStatuses.delete(reference.id);
          render();
        }
      });
      const actions = element('div', '', row, 'reference-actions');
      if (reference.url) {
        const open = link('Open link', reference.url, actions, 'button secondary');
        open.target = '_blank'; open.rel = 'noopener noreferrer';
      }
      if (reference.sourceUrl && reference.sourceUrl !== reference.url) {
        const source = link('Scholarly source', reference.sourceUrl, actions, 'button secondary');
        source.target = '_blank'; source.rel = 'noopener noreferrer';
      }
      if (!noteDrafts.has(reference.id)) {
        const notesButton = element('button', reference.notes ? 'Edit notes' : 'Add notes', actions, 'secondary');
        notesButton.type = 'button';
        notesButton.dataset.notesFor = reference.id;
        notesButton.addEventListener('click', () => {
          const saved = reference.notes || '';
          noteDrafts.set(reference.id, {text: saved, saved, state: 'idle', error: ''});
          toolbarStatus.textContent = '';
          render();
          list.querySelector(`textarea[data-note-for="${reference.id}"]`)?.focus();
        });
      }
      if (reference.manual) {
        element('button', 'Edit', actions, 'secondary').addEventListener('click', () => openForm(reference));
      }
      element('button', 'Remove', actions, 'secondary').addEventListener('click', async () => {
        const draft = noteDrafts.get(reference.id);
        const what = `“${reference.title || 'this reference'}”${draft && unsaved(draft) ? ' and its unsaved notes' : ''}`;
        if (!window.confirm(`Remove ${what} from this project?`)) return;
        try {
          await api(`${projectPath}/${reference.id}`, {method: 'DELETE'});
          noteDrafts.delete(reference.id);
          await refresh();
        } catch (error) { showError(error); }
      });
    }
    if (focusedNote) {
      const textarea = list.querySelector(`textarea[data-note-for="${focusedNote.id}"]`);
      if (textarea) { textarea.focus(); textarea.setSelectionRange(focusedNote.start, focusedNote.end); }
    }
  }
  function notesEditor(reference, row) {
    const draft = noteDrafts.get(reference.id);
    const editor = element('div', '', row, 'reference-notes-editor');
    const label = element('label', 'Notes', editor);
    const textarea = element('textarea', '', label);
    textarea.maxLength = 5000; textarea.rows = 4;
    textarea.value = draft.text; textarea.dataset.noteFor = reference.id;
    textarea.readOnly = draft.state === 'saving';
    const footer = element('div', '', editor, 'reference-notes-footer');
    const counter = element('span', '', footer, 'reference-notes-counter');
    const status = element('span', '', footer, 'reference-save-status');
    status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
    const save = element('button', 'Save notes', footer);
    save.type = 'button';
    const cancel = element('button', 'Cancel', footer, 'secondary');
    cancel.type = 'button';
    function update() {
      counter.textContent = `${draft.text.length} / 5000`;
      status.textContent = draft.state === 'saving' ? 'Saving…'
        : draft.state === 'error' ? `Not saved: ${draft.error}`
          : unsaved(draft) ? 'Unsaved changes' : '';
      save.disabled = cancel.disabled = draft.state === 'saving';
    }
    update();
    textarea.addEventListener('input', () => { draft.text = textarea.value; update(); });
    cancel.addEventListener('click', () => {
      noteDrafts.delete(reference.id);
      render();
      list.querySelector(`button[data-notes-for="${reference.id}"]`)?.focus();
    });
    save.addEventListener('click', async () => {
      draft.state = 'saving';
      render();
      try {
        const updated = await api(`${projectPath}/${reference.id}`, {
          method: 'PATCH', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({notes: draft.text}),
        });
        references = references.map(item => item.id === updated.id ? updated : item);
        noteDrafts.delete(reference.id);
        toolbarStatus.textContent = 'Notes saved';
        render();
      } catch (error) {
        Object.assign(draft, {state: 'error', error: error.message});
        render();
      }
    });
  }
  const ready = refresh({notify: false}).catch(showError);
  return {refresh, ready, isSaved: paper => savedIds.has(paper.id) ||
    Boolean(paper.doi && savedDois.has(doiKey(paper.doi)))};
}
function literature(project, left, aside, actions, remove, referenceLibrary) {
  const searchButton = element('button', 'Find papers', actions, 'discovery-search-button');
  searchButton.hidden = !project.researchQuestion;
  searchButton.prepend(icon('search'));
  const papersPanel = panel(left, 'Papers', 'document');
  const papersBody = element('div', '', papersPanel);
  const searchNotice = element('div', '', aside, 'search-notice');
  searchNotice.setAttribute('role', 'status');
  const searchPanel = element('details', '', aside, 'search-disclosure');
  searchPanel.hidden = !project.researchQuestion;
  searchPanel.open = true;
  element('summary', 'Literature search', searchPanel);
  let searchDisclosureInitialized = false;
  searchPanel.querySelector('summary').addEventListener('click', () => { searchDisclosureInitialized = true; });
  const searchBody = element('div', '', searchPanel);
  element('p', 'Loading saved papers…', papersBody, 'muted');
  let busy = false;
  let pendingSearch = false;
  let noEnabledQueries = false;
  let timer;
  let refreshVersion = 0;
  let displayedRunId;
  let showSetAside = false;
  let openAccessOnly = false;
  let paperSort = 'relevance';
  // Selected cluster tab, kept across re-renders: 'all' or a group's clusterId (null = Uncategorized).
  let activeGroup = 'all';
  const projectPath = `/${project.id}`;
  function patchAndRefresh(path, body) {
    if (busy) return Promise.resolve();
    errorBox.hidden = true;
    return api(path, {method: 'PATCH', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)})
      .then(() => refresh())
      .catch(async error => {
        if (error.status === 409) { closeDrawer(); await refresh(); }
        showError(error);
      });
  }
  const editLink = actions.querySelector('a');
  editLink.classList.add('secondary');
  function setBusy(value) {
    value = value || pendingSearch;
    busy = value;
    document.querySelectorAll(".drawer-organize select, .drawer-organize button, .subtopic-menu button, .subtopic-menu select, .rename-form input, .rename-form textarea, .rename-form button, .query-controls input, .query-controls button").forEach(control => { control.disabled = value; });
    searchButton.disabled = value || noEnabledQueries || !project.researchQuestion;
    searchButton.textContent = value ? 'Searching papers…' : 'Find papers';
    if (!value) searchButton.prepend(icon('search'));
    remove.disabled = value;
    editLink.setAttribute('aria-disabled', String(value));
  }
  editLink.addEventListener('click', event => { if (busy) event.preventDefault(); });
  const drawer = element('div', '', document.body, 'drawer');
  drawer.hidden = true;
  const backdrop = element('div', '', drawer, 'drawer-backdrop');
  const drawerPanel = element('aside', '', drawer, 'drawer-panel');
  drawerPanel.setAttribute('role', 'dialog');
  drawerPanel.setAttribute('aria-modal', 'true');
  drawerPanel.setAttribute('aria-label', 'Paper details');
  drawerPanel.tabIndex = -1;
  let drawerReturnFocus = null;
  function closeDrawer() {
    drawer.hidden = true;
    document.removeEventListener('keydown', drawerKey);
    if (drawerReturnFocus) drawerReturnFocus.focus();
  }
  function drawerKey(event) { if (event.key === 'Escape') closeDrawer(); }
  backdrop.addEventListener('click', closeDrawer);
  function drawerField(label, value, options = {}) {
    if (!value) return;
    const row = element('div', '', drawerPanel, 'drawer-field');
    element('dt', label, row);
    const dd = element('dd', options.href ? '' : value, row);
    if (options.href) {
      const anchor = link(value, options.href, dd);
      anchor.target = '_blank';
      anchor.rel = 'noopener noreferrer';
    }
  }
  function openDrawer(paper, named, clusterOptions) {
    drawerReturnFocus = document.activeElement;
    drawerPanel.replaceChildren();
    const head = element('div', '', drawerPanel, 'drawer-head');
    element('span', 'Paper details', head, 'query-label');
    element('button', 'Close', head, 'secondary').addEventListener('click', closeDrawer);
    element('h2', paper.title || 'Title unavailable', drawerPanel, 'drawer-title');
    const save = element('button', referenceLibrary.isSaved(paper) ? 'Saved to references' : 'Save reference', drawerPanel, 'secondary save-reference');
    save.disabled = referenceLibrary.isSaved(paper);
    save.addEventListener('click', async () => {
      save.disabled = true;
      try {
        await api(`${projectPath}/references/from-paper/${paper.id}`, {method: 'POST'});
        await referenceLibrary.refresh();
        save.textContent = 'Saved to references';
      } catch (error) { save.disabled = false; showError(error); }
    });
    if (clusterOptions && clusterOptions.length) {
      const organize = element('div', '', drawerPanel, 'drawer-organize');
      const moveLabel = element('label', 'Subtopic ', organize);
      const move = element('select', '', moveLabel);
      for (const option of clusterOptions) {
        const el = element('option', option.label, move);
        el.value = option.id === null ? '' : String(option.id);
      }
      move.disabled = busy;
      move.value = paper.clusterId === null || paper.clusterId === undefined ? '' : String(paper.clusterId);
      move.addEventListener('change', () => {
        patchAndRefresh(`${projectPath}/papers/${paper.id}`,
          {clusterId: move.value === '' ? null : Number(move.value)});
        closeDrawer();
      });
      const relevance = element('button', paper.isRelevant === false ? 'Restore to results' : 'Set aside as irrelevant',
        organize, 'secondary');
      relevance.disabled = busy;
      relevance.addEventListener('click', () => {
        patchAndRefresh(`${projectPath}/papers/${paper.id}`, {isRelevant: paper.isRelevant === false});
        closeDrawer();
      });
    }
    const authors = paper.authors.map(author => author.name).filter(Boolean);
    drawerField('Authors', authors.length ? authors.join(', ') : 'Not available');
    drawerField('Published', [paper.publicationDate || paper.publicationYear, paper.venue || paper.journal]
      .filter(Boolean).join(' · ') || 'Not available');
    drawerField('Publisher', paper.publisher);
    drawerField('Citations', paper.citationCount ?? 'Not available');
    drawerField('Relevance', `${Math.round((paper.relevanceScore ?? 0) * 100)}%`);
    const topic = named && named.get(paper.clusterId);
    drawerField('Cluster', topic ? topic.name
      : paper.clusterId === null || paper.clusterId === undefined ? 'Uncategorized'
      : `Cluster ${paper.clusterId + 1}`);
    element('h3', 'Access & links', drawerPanel);
    const access = element('p', '', drawerPanel, 'access-line');
    access.append(accessBadge(paper.accessStatus));
    element('span', ACCESS_LABEL[paper.accessStatus] || 'Access unknown', access, 'access-note');
    drawerField('DOI', paper.doi, {href: paper.doiUrl || (paper.doi && `https://doi.org/${paper.doi}`)});
    drawerField('Source', `View on ${paper.source}`, {href: paper.sourceUrl});
    drawerField('Publication', 'Open publication page', {href: paper.publicationUrl});
    if (paper.openAccessUrl) drawerField('Free full text', 'Open the available copy', {href: paper.openAccessUrl});
    if (topic) explanationSection(paper, topic.name);
    element('h3', 'Abstract', drawerPanel);
    element('p', paper.abstract || 'No abstract is available for this paper.', drawerPanel,
      paper.abstract ? 'drawer-abstract' : 'muted');
    drawer.hidden = false;
    document.addEventListener('keydown', drawerKey);
    drawerPanel.focus();
  }
  function explanationSection(paper, subtopicName) {
    element('h3', `Why it's in ${subtopicName}`, drawerPanel);
    const body = element('p', '', drawerPanel, 'drawer-abstract');
    const load = () => {
      body.replaceChildren();
      body.className = 'drawer-abstract muted';
      body.textContent = 'Generating an explanation…';
      api(`${projectPath}/papers/${paper.id}/explanation`, {method: 'POST'}).then(result => {
        paper.classificationExplanation = result.explanation;
        body.className = 'drawer-abstract';
        body.textContent = result.explanation;
      }).catch(async error => {
        if (error.status === 409) {
          closeDrawer();
          await refresh();
          showError(error);
          return;
        }
        body.className = 'drawer-abstract';
        body.replaceChildren();
        element('span', `Could not generate an explanation. ${error.message} `, body, 'search-failure');
        element('button', 'Retry', body, 'secondary drawer-retry').addEventListener('click', load);
      });
    };
    load();
  }
  function showPapers(papers, history, subtopics) {
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
      if (completed.duplicateCount) element('p', `${completed.duplicateCount} duplicate ${completed.duplicateCount === 1 ? 'record was' : 'records were'} merged by DOI, identifier, or title.`, papersBody, 'field-help');
      if (completed.filteredCount) element('p', `${completed.filteredCount} low-relevance ${completed.filteredCount === 1 ? 'paper was' : 'papers were'} filtered out before clustering.`, papersBody, 'field-help');
      const topicCount = (subtopics || []).length;
      const oaCount = papers.filter(p => p.accessStatus === 'OPEN_ACCESS').length;
      element('p', `${papers.length} ${papers.length === 1 ? 'paper' : 'papers'} · ${topicCount || 'no'} ${topicCount === 1 ? 'subtopic' : 'subtopics'} · ${oaCount} open access · ${yearRange(completed.parameters)}`, papersBody, 'research-summary');
    }
    if (!papers.length) {
      const empty = element('div', '', papersBody, 'empty-state');
      empty.append(icon('search'));
      element('h3', completed ? 'No papers matched this search' : project.researchQuestion ? 'Explore the literature' : 'No discovery results yet', empty);
      element('p', completed ? 'Try a shorter research topic or a wider year range.'
        : project.researchQuestion ? 'Find real scholarly papers using your research question.'
          : 'Add a research description to discover papers.', empty, 'muted');
      return;
    }
    const named = new Map((subtopics || []).map(topic => [topic.clusterId, topic]));
    const setAside = papers.filter(p => p.isRelevant === false);
    let visible = showSetAside ? papers : papers.filter(p => p.isRelevant !== false);
    if (openAccessOnly) visible = visible.filter(p => p.accessStatus === 'OPEN_ACCESS');
    const filters = element('div', '', papersBody, 'paper-filters');
    if (setAside.length) {
      const toggle = element('button', showSetAside
        ? `Hide ${setAside.length} set aside` : `Show ${setAside.length} set aside`,
        filters, 'secondary set-aside-toggle');
      toggle.addEventListener('click', () => { showSetAside = !showSetAside; refresh().catch(showError); });
    }
    const oaToggle = element('button', 'Open access only',
      filters, `secondary set-aside-toggle${openAccessOnly ? ' active' : ''}`);
    oaToggle.setAttribute('aria-pressed', String(openAccessOnly));
    oaToggle.addEventListener('click', () => { openAccessOnly = !openAccessOnly; refresh().catch(showError); });
    const sortSelect = element('select', '', filters, 'paper-sort-select');
    sortSelect.setAttribute('aria-label', 'Sort papers');
    for (const [value, label] of [
      ['relevance', 'Sort: Most relevant'],
      ['citations', 'Sort: Most cited'],
      ['newest', 'Sort: Newest first'],
      ['oldest', 'Sort: Oldest first'],
      ['title', 'Sort: Title A–Z'],
    ]) element('option', label, sortSelect).value = value;
    sortSelect.value = paperSort;
    const clusterIds = [...new Set([...named.keys(), ...papers.map(paper => paper.clusterId)])]
      .filter(id => id !== null && id !== undefined)
      .sort((a, b) => a - b);
    const groups = clusterIds.map(id => ({
      id,
      name: named.get(id)?.name || `Cluster ${id + 1}`,
      topic: named.get(id) || null,
      members: visible.filter(p => p.clusterId === id),
    }));
    const uncategorized = visible.filter(p => p.clusterId === null || p.clusterId === undefined);
    groups.push({id: null, name: 'Uncategorized', topic: null, members: uncategorized});
    const clusterOptions = groups.map(group => ({id: group.id, label: group.name}));
    if (completed && completed.namingError) {
      element('p', 'Automatic cluster names were unavailable for this search.', papersBody, 'field-help');
    }
    const tabRow = element('div', '', papersBody, 'cluster-tabs');
    const subtopicActions = element('div', '', papersBody, 'subtopic-actions');
    element('span', 'Subtopic organization', subtopicActions, 'subtopic-actions-label');
    const createSubtopic = element('button', 'Create subtopic', subtopicActions, 'secondary');
    createSubtopic.disabled = busy;
    createSubtopic.addEventListener('click', async () => {
      const name = window.prompt('Subtopic name');
      if (!name || !name.trim()) return;
      const description = window.prompt('Description (optional)', '') ?? '';
      try {
        await api(`${projectPath}/subtopics`, {
          method: 'POST', body: JSON.stringify({name: name.trim(), description}),
        });
        await refresh();
      } catch (error) { showError(error); }
    });
    const detail = element('div', '', papersBody);
    const results = element('section', '', papersBody, 'paper-results');
    const resultsHeading = element('div', '', results, 'paper-results-heading');
    const resultsTitle = element('h3', '', resultsHeading);
    const resultsCount = element('span', '', resultsHeading, 'paper-results-count');
    const list = element('div', '', results, 'paper-list');
    let active = null;
    const allButton = element('button', '', tabRow, 'cluster-tab');
    element('span', 'All', allButton);
    element('span', String(visible.length), allButton, 'count');
    allButton.addEventListener('click', () => select(null));
    const buttons = groups.map((group, index) => {
      const button = element('button', '', tabRow, 'cluster-tab');
      button.title = group.name;
      element('span', group.name, button, 'cluster-tab-name');
      element('span', String(group.members.length), button, 'count');
      button.addEventListener('click', () => select(index));
      return button;
    });
    function select(index) {
      active = index;
      activeGroup = index === null ? 'all' : groups[index].id;
      allButton.classList.toggle('active', index === null);
      buttons.forEach((button, i) => button.classList.toggle('active', i === index));
      detail.replaceChildren();
      list.replaceChildren();
      const group = index === null ? null : groups[index];
      if (group && group.topic) subtopicHeader(group.topic, detail, subtopics || []);
      const selectedPapers = sortedPapers(group ? group.members : visible, paperSort);
      resultsTitle.textContent = group ? group.name : 'All papers';
      resultsCount.textContent = `${selectedPapers.length} ${selectedPapers.length === 1 ? 'result' : 'results'}`;
      for (const paper of selectedPapers) {
        paperRow(paper, list, named, clusterOptions);
      }
    }
    sortSelect.addEventListener('change', () => { paperSort = sortSelect.value; select(active); });
    const restored = activeGroup === 'all' ? -1 : groups.findIndex(group => group.id === activeGroup);
    select(restored >= 0 ? restored : null);
  }
  function subtopicHeader(topic, wrap, topics) {
    wrap.replaceChildren();
    const text = element('p', topic.description, wrap, 'cluster-description');
    if (topic.userModified) element('span', 'edited', text, 'edit-tag');
    if (topic.keywords.length) {
      const keywords = element('div', '', wrap, 'keyword-list');
      for (const keyword of topic.keywords) element('span', keyword, keywords, 'keyword');
    }
    const management = element('details', '', wrap, 'subtopic-menu');
    element('summary', 'Manage subtopic', management);
    const menu = element('div', '', management, 'subtopic-menu-items');
    const editButton = element('button', 'Rename subtopic', menu, 'secondary');
    editButton.disabled = busy;
    editButton.addEventListener('click', () => {
      wrap.replaceChildren();
      const form = element('form', '', wrap, 'rename-form');
      const name = element('input', '', form);
      name.value = topic.name;
      name.required = true;
      name.maxLength = 80;
      const description = element('textarea', '', form);
      description.value = topic.description;
      description.maxLength = 500;
      const formActions = element('div', '', form, 'form-actions');
      element('button', 'Save', formActions);
      element('button', 'Cancel', formActions, 'secondary').addEventListener('click', event => {
        event.preventDefault();
        subtopicHeader(topic, wrap, topics);
      });
      form.addEventListener('submit', event => {
        event.preventDefault();
        patchAndRefresh(`${projectPath}/subtopics/${topic.clusterId}`,
          {name: name.value, description: description.value});
      });
      name.focus();
    });
    const deleteButton = element('button', 'Delete subtopic', menu, 'secondary');
    deleteButton.disabled = busy;
    deleteButton.addEventListener('click', async () => {
      if (!window.confirm(`Delete ${topic.name}? Its papers will become uncategorized.`)) return;
      try { await api(`${projectPath}/subtopics/${topic.clusterId}`, {method: 'DELETE'}); await refresh(); }
      catch (error) { showError(error); }
    });
    const mergeTargets = topics.filter(item => item.clusterId !== topic.clusterId);
    if (mergeTargets.length) {
      const merge = element('select', '', menu, 'merge-subtopic');
      element('option', 'Merge into…', merge).disabled = true;
      for (const target of mergeTargets) element('option', target.name, merge).value = target.clusterId;
      merge.disabled = busy;
      merge.addEventListener('change', async () => {
        try {
          await api(`${projectPath}/subtopics/${topic.clusterId}/merge`, {
            method: 'POST', body: JSON.stringify({targetClusterId: Number(merge.value)}),
          });
          await refresh();
        } catch (error) { showError(error); }
      });
    }
  }
  function paperRow(paper, parent, named, clusterOptions) {
    const row = element('article', '', parent, 'project-row paper-row');
    if (paper.isRelevant === false) row.classList.add('set-aside');
    row.tabIndex = 0;
    row.setAttribute('role', 'button');
    const titleRow = element('div', '', row, 'paper-title-row');
    element('h3', paper.title || 'Title unavailable', titleRow);
    titleRow.append(accessBadge(paper.accessStatus));
    const authors = paper.authors.map(author => author.name).filter(Boolean);
    const authorLabel = authors.length ? authors.slice(0, 3).join(', ') + (authors.length > 3 ? ' et al.' : '') : 'Authors unavailable';
    element('p', `${authorLabel} · ${paper.publicationYear ?? 'Year unavailable'}`, row, 'paper-metadata');
    if (paper.venue) element('p', paper.venue, row, 'paper-metadata');
    if (paper.doi) element('p', `DOI: ${paper.doi}`, row, 'paper-doi');
    const topic = named.get(paper.clusterId);
    if (topic) inlineExplanation(paper, topic.name, row);
    const footer = element('div', '', row, 'project-meta');
    element('span', `Relevance: ${Math.round((paper.relevanceScore ?? 0) * 100)}% · Citations: ${paper.citationCount ?? 'Unavailable'} · ${paper.source}`, footer);
    const save = element('button', referenceLibrary.isSaved(paper) ? 'Saved' : 'Save reference', footer, 'secondary card-save');
    save.disabled = referenceLibrary.isSaved(paper);
    save.addEventListener('click', async event => {
      event.stopPropagation();
      save.disabled = true;
      try {
        await api(`${projectPath}/references/from-paper/${paper.id}`, {method: 'POST'});
        await referenceLibrary.refresh();
        save.textContent = 'Saved';
      } catch (error) { save.disabled = false; showError(error); }
    });
    const details = element('span', 'View details', footer, 'open-link');
    details.append(icon('arrow'));
    const open = () => openDrawer(paper, named, clusterOptions);
    row.addEventListener('click', event => { if (!event.target.closest('a')) open(); });
    row.addEventListener('keydown', event => {
      if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); open(); }
    });
  }
  function inlineExplanation(paper, subtopicName, row) {
    const wrap = element('div', '', row, 'card-explanation');
    const body = element('p', '', wrap, 'card-explanation-body');
    const show = text => {
      body.replaceChildren();
      body.textContent = text;
    };
    if (paper.classificationExplanation) show(paper.classificationExplanation);
    else body.textContent = 'Explanation available on request.';
    const button = element('button', paper.classificationExplanation ? 'Refresh explanation' : 'Why is this here?', wrap, 'secondary card-explanation-button');
    button.addEventListener('click', async event => {
      event.stopPropagation();
      button.disabled = true;
      show('Generating an explanation…');
      try {
        const result = await api(`${projectPath}/papers/${paper.id}/explanation`, {method: 'POST'});
        paper.classificationExplanation = result.explanation;
        show(result.explanation);
        button.textContent = 'Refresh explanation';
      } catch (error) {
        if (error.status === 409) {
          await refresh();
          return;
        }
        show(`Could not generate an explanation. ${error.message}`);
        button.textContent = 'Retry';
      } finally { button.disabled = false; }
    });
  }
  function showSearch(history, savedQueries) {
    noEnabledQueries = Boolean(savedQueries?.length) && !savedQueries.some(item => item.enabled);
    searchBody.replaceChildren();
    searchNotice.replaceChildren();
    if (!searchDisclosureInitialized) {
      searchPanel.open = !history.some(run => run.status === 'COMPLETED');
      searchDisclosureInitialized = true;
    }
    const latest = history[0];
    setBusy(latest?.status === 'SEARCHING');
    element('p', 'The scholarly source searches the enabled queries below with the saved year range. Your description guides suggestions and relevance but is never searched directly.', searchBody, 'field-help');
    element('span', 'Description', searchBody, 'query-label');
    element('p', latest?.parameters.query ?? project.researchQuestion, searchBody, 'search-query');
    const queryControls = element('div', '', searchBody, 'query-controls');
    element('span', 'Search queries', queryControls, 'query-label');
    const queryRequest = async (path, options) => {
      errorBox.hidden = true;
      try {
        await api(`${projectPath}/queries${path}`, {headers: {'Content-Type': 'application/json'}, ...options});
      } catch (error) {
        showError(error);
        // A 409 means a search started underneath us; re-render to reflect the locked state.
        if (error.status === 409) await refresh();
        return false;
      }
      await refresh();
      return true;
    };
    if (!savedQueries?.length) {
      element('p', 'Queries are suggested from your description on the first search, or suggest them now.', queryControls, 'field-help');
    }
    for (const saved of savedQueries ?? []) {
      const row = element('div', '', queryControls, 'query-option');
      const checkbox = element('input', '', row);
      checkbox.type = 'checkbox';
      checkbox.checked = saved.enabled;
      checkbox.disabled = busy;
      checkbox.setAttribute('aria-label', `Include ${saved.query}`);
      checkbox.addEventListener('change', async () => {
        const ok = await queryRequest(`/${saved.id}`, {method: 'PATCH', body: JSON.stringify({enabled: checkbox.checked})});
        if (!ok) checkbox.checked = saved.enabled;
      });
      const text = element('input', '', row, 'query-text');
      text.value = saved.query;
      text.setAttribute('value', saved.query);
      text.maxLength = 160;
      text.disabled = busy;
      text.setAttribute('aria-label', 'Search query');
      text.addEventListener('change', async () => {
        const value = text.value.trim();
        if (!value || value === saved.query) { text.value = saved.query; return; }
        const ok = await queryRequest(`/${saved.id}`, {method: 'PATCH', body: JSON.stringify({query: value})});
        if (!ok) text.value = saved.query;
      });
      if (saved.userAdded) {
        element('span', 'Yours', row, 'query-tag');
        const remove = element('button', '×', row, 'secondary query-remove');
        remove.type = 'button';
        remove.disabled = busy;
        remove.setAttribute('aria-label', `Remove ${saved.query}`);
        remove.addEventListener('click', () => queryRequest(`/${saved.id}`, {method: 'DELETE'}));
      }
    }
    if (noEnabledQueries) element('p', 'Enable at least one search query.', searchNotice, 'search-failure');
    const addForm = element('form', '', queryControls, 'query-add');
    const addInput = element('input', '', addForm);
    addInput.placeholder = 'Add a search query';
    addInput.maxLength = 160;
    addInput.disabled = busy;
    const addButton = element('button', 'Add', addForm, 'secondary');
    addButton.disabled = busy;
    addForm.addEventListener('submit', event => {
      event.preventDefault();
      const value = addInput.value.trim();
      if (value) queryRequest('/custom', {method: 'POST', body: JSON.stringify({query: value})});
    });
    const suggest = element('button', savedQueries?.length ? 'Regenerate suggestions' : 'Suggest queries', queryControls, 'secondary');
    suggest.disabled = busy;
    suggest.addEventListener('click', async () => {
      suggest.disabled = true;
      try { await api(`${projectPath}/queries`, {method: 'POST'}); await refresh(); }
      catch (error) { showError(error); suggest.disabled = false; }
    });
    if (latest?.generatedQueries?.length) {
      element('span', 'Queries used for this search', searchBody, 'query-label');
      const queries = element('ul', '', searchBody, 'generated-queries');
      for (const query of latest.generatedQueries) element('li', query, queries);
    }
    if (latest?.failedQueries?.length) {
      element('p', `${latest.failedQueries.length} of ${latest.generatedQueries.length} queries failed; results come from the rest.`, searchNotice, 'field-help');
    }
    if (latest?.failedSources?.length) {
      const joinNames = (names) => names.length < 2 ? names.join('')
        : `${names.slice(0, -1).join(', ')} and ${names.at(-1)}`;
      // A source may have failed on only some queries, so do not claim which source the results came from.
      element('p', `${joinNames(latest.failedSources)} ${latest.failedSources.length > 1 ? 'were' : 'was'} unavailable for one or more queries; results may be incomplete.`, searchNotice, 'field-help');
    }
    if (!latest) {
      element('p', pendingSearch ? 'Searching scholarly papers…' : 'No search has been run yet.', searchNotice, 'search-status');
      return;
    }
    element('p', busy ? (SEARCH_STAGES[latest.stage] || 'Searching scholarly papers…')
      : latest.status === 'FAILED' ? latest.errorMessage
      : `${latest.paperCount} papers saved · ${latest.clusterCount} ${latest.clusterCount === 1 ? 'cluster' : 'clusters'} · ${latest.totalFound.toLocaleString()} matches in ${latest.provider}`,
      searchNotice, latest.status === 'FAILED' ? 'search-failure' : 'search-status');
    if (latest.status === 'FAILED' && history.some(run => run.status === 'COMPLETED')) {
      element('p', 'Results from your last successful search are still available.', searchNotice, 'field-help');
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
    await referenceLibrary.ready;
    const version = ++refreshVersion;
    clearTimeout(timer);
    const history = await api(`${projectPath}/searches`);
    if (version !== refreshVersion) return;
      const queries = await api(`${projectPath}/queries`);
      showSearch(history, queries);
    const latestId = history[0]?.id ?? null;
    if (!busy || displayedRunId === undefined) {
      const [papers, subtopics] = await Promise.all([
        api(`${projectPath}/papers`),
        api(`${projectPath}/subtopics`),
      ]);
      if (version !== refreshVersion) return;
      showPapers(papers, history, subtopics);
      displayedRunId = latestId;
    }
    if (busy) schedulePoll();
  }
  // Any refresh can cancel the poll timer, so every failed refresh must resume polling.
  function refreshOrRetry() {
    return refresh().catch(error => {
      showError(error);
      if (busy) schedulePoll();
    });
  }
  function schedulePoll() {
    clearTimeout(timer);
    timer = setTimeout(refreshOrRetry, 500);
  }
  async function runSearch(force) {
    clearTimeout(timer);
    ++refreshVersion;
    pendingSearch = true;
    setBusy(true);
    schedulePoll();
    errorBox.hidden = true;
    searchNotice.replaceChildren();
    element('p', 'Searching scholarly papers and organizing results…', searchNotice, 'search-status');
    try {
      await api(`${projectPath}/search${force ? '?force=true' : ''}`, {method: 'POST'});
    } catch (error) {
      ++refreshVersion;
      pendingSearch = false;
      clearTimeout(timer);
      if (error.code === 'MANUAL_EDITS_PRESENT') {
        setBusy(false);
        searchNotice.replaceChildren();
        element('p', 'This project has manual changes. A new search will replace them.', searchNotice, 'search-failure');
        element('button', 'Run anyway', searchNotice, 'secondary').addEventListener('click', () => runSearch(true));
        return;
      }
      showError(error);
    }
    ++refreshVersion;
    pendingSearch = false;
    clearTimeout(timer);
    setBusy(false);
    closeDrawer();
    try { await refresh(); } catch (error) { showError(error); }
  }
  searchButton.addEventListener('click', () => runSearch(false));
  window.addEventListener('references-changed', refreshOrRetry);
  refresh().catch(error => {
    papersBody.replaceChildren();
    element('p', 'Unable to load saved papers. Refresh to try again.', papersBody, 'muted');
    showError(error);
  });
}
async function render() {
  const parts = location.pathname.split('/').filter(Boolean);
  const currentNav = document.querySelector(`[data-nav="${parts[0] === 'settings' ? 'settings' : parts[1] === 'new' ? 'new' : 'library'}"]`);
  currentNav.setAttribute('aria-current', 'page');
  if (!parts.length) {
    const projects = await api();
    content.replaceChildren();
    dashboard(projects);
  } else if (parts[1] === 'new') {
    content.replaceChildren();
    projectForm();
  } else if (parts[0] === 'settings') {
    content.replaceChildren();
    await settings();
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
