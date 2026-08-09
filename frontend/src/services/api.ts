const BASE =

  (typeof process !== 'undefined' && process.env.EXPO_PUBLIC_BACKEND_URL) ||

  'http://localhost:8000';



async function req<T>(path: string, init?: RequestInit): Promise<T> {

  const res = await fetch(`${BASE}${path}`, {

    ...init,

    headers: {

      'Content-Type': 'application/json',

      ...(init?.headers || {}),

    },

  });

  const data = await res.json().catch(() => ({}));

  if (!res.ok) {

    const detail = (data as any)?.detail;

    let msg: string;

    if (typeof detail === 'string') msg = detail;

    else if (Array.isArray(detail))

      msg = detail.map((d) => d?.msg || JSON.stringify(d)).join('; ');

    else msg = (data as any)?.message || res.statusText || 'Errore';

    throw new Error(msg);

  }

  return data as T;

}



export type Account = {

  id: string;

  type: 'google' | 'microsoft' | 'imap' | 'pec';

  label: string;

  address: string;

  color: string;

  pec_provider?: string | null;

  last_sync_at?: string | null;

  sync_state?: string;

  last_sync_error?: string | null;

  imap_host?: string | null;

  imap_port?: number | null;

  imap_user?: string | null;

  smtp_host?: string | null;

  smtp_port?: number | null;

  auth_method?: string | null;

};



export type MessageListItem = {

  id: string;

  account_id: string;

  subject: string;

  from: string;

  to: string[];

  date?: string;

  flags?: { seen?: boolean; flagged?: boolean; archived?: boolean };

  has_attachments?: boolean;

  is_pec?: boolean;

  snippet?: string;

  priority?: string | null;

  folder?: string;

};



export const api = {

  checkSetup: (email?: string) =>

    req<{ setup_done: boolean; email: string }>(

      `/api/auth/check_setup${email ? `?email=${encodeURIComponent(email)}` : ''}`,

    ),

  setup: (email: string, master_password: string) =>

    req<{ email: string }>('/api/auth/setup', {

      method: 'POST',

      body: JSON.stringify({ email, master_password }),

    }),

  login: (email: string, master_password: string) =>

    req<{ email: string }>('/api/auth/login', {

      method: 'POST',

      body: JSON.stringify({ email, master_password }),

    }),

  listAccounts: (email: string, master_password: string) =>

    req<Account[]>(

      `/api/accounts?email=${encodeURIComponent(email)}&master_password=${encodeURIComponent(master_password)}`,

    ),

  pecPresets: () => req<Record<string, unknown>>('/api/accounts/pec-presets'),

  addImapAccount: (body: Record<string, unknown>) =>

    req<Account>('/api/accounts/imap', { method: 'POST', body: JSON.stringify(body) }),

  updateImapAccount: (id: string, body: Record<string, unknown>) =>

    req<Account>(`/api/accounts/${id}`, { method: 'PUT', body: JSON.stringify(body) }),

  deleteAccount: (id: string, email: string, master_password: string) =>

    req(`/api/accounts/${id}?email=${encodeURIComponent(email)}&master_password=${encodeURIComponent(master_password)}`, {

      method: 'DELETE',

    }),

  testAccount: (id: string, email: string, master_password: string) =>

    req<{ ok: boolean; inbox_count?: number }>(

      `/api/accounts/${id}/test?email=${encodeURIComponent(email)}&master_password=${encodeURIComponent(master_password)}`,

      { method: 'POST' },

    ),

  oauthStatus: () =>
    req<{
      google: { configured: boolean; redirect_uri: string; client_id?: string };
      microsoft: { configured: boolean; redirect_uri: string; client_id?: string };
    }>('/api/accounts/oauth/status'),

  oauthStart: (provider: 'google' | 'microsoft', email: string, master_password: string) =>

    req<{ authorize_url: string; state: string; provider: string }>(

      `/api/accounts/oauth/${provider}/start`,

      {

        method: 'POST',

        body: JSON.stringify({ email, master_password }),

      },

    ),

  oauthComplete: (

    provider: 'google' | 'microsoft',

    body: { email: string; master_password: string; code: string; state: string },

  ) =>

    req<Account>(`/api/accounts/oauth/${provider}/complete`, {

      method: 'POST',

      body: JSON.stringify(body),

    }),

  listMessages: (params: {

    email: string;

    master_password: string;

    account?: string;

    q?: string;

    unread?: boolean;

    pec?: boolean;

    folder?: string;

  }) => {

    const sp = new URLSearchParams({

      email: params.email,

      master_password: params.master_password,

    });

    if (params.account) sp.set('account', params.account);

    if (params.q) sp.set('q', params.q);

    if (params.unread) sp.set('unread', 'true');

    if (params.pec) sp.set('pec', 'true');

    if (params.folder) sp.set('folder', params.folder);

    return req<{ items: MessageListItem[]; total: number }>(`/api/messages?${sp}`);

  },

  getMessage: (id: string, email: string, master_password: string) =>

    req<any>(

      `/api/messages/${id}?email=${encodeURIComponent(email)}&master_password=${encodeURIComponent(master_password)}`,

    ),

  trashMessage: (id: string, email: string, master_password: string) =>

    req<{ ok: boolean; folder: string }>(`/api/messages/${id}/trash`, {

      method: 'POST',

      body: JSON.stringify({ email, master_password }),

    }),

  restoreMessage: (id: string, email: string, master_password: string) =>

    req<{ ok: boolean; folder: string }>(`/api/messages/${id}/restore`, {

      method: 'POST',

      body: JSON.stringify({ email, master_password }),

    }),

  deleteMessage: (id: string, email: string, master_password: string) =>

    req<{ ok: boolean }>(

      `/api/messages/${id}?email=${encodeURIComponent(email)}&master_password=${encodeURIComponent(master_password)}`,

      { method: 'DELETE' },

    ),

  sendMessage: (body: Record<string, unknown>) =>

    req<any>('/api/messages/send', { method: 'POST', body: JSON.stringify(body) }),

  syncRun: (email: string, master_password: string) =>

    req(

      `/api/sync/run?email=${encodeURIComponent(email)}&master_password=${encodeURIComponent(master_password)}`,

      { method: 'POST' },

    ),

  listRules: (email: string, master_password: string) =>

    req<any[]>(

      `/api/rules?email=${encodeURIComponent(email)}&master_password=${encodeURIComponent(master_password)}`,

    ),

  createRule: (body: Record<string, unknown>) =>

    req('/api/rules', { method: 'POST', body: JSON.stringify(body) }),

};


