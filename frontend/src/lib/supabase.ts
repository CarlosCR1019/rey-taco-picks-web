import { createClient } from '@supabase/supabase-js';

const url = import.meta.env.VITE_SUPABASE_URL || 'https://dqwuaocyyohwkkuldsmp.supabase.co';
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY || 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBpYmFzZSIsInJlZiI6ImRxd3Vhb2N5eW9od2trdWxkc21wIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODY2NzQ3OTAsImV4cCI6MjEwMjI1MDc5MH0.bKBhyFHtcAXYgx44rg4-D2CaqktOnUg6ZnvBcTW1CDQ';

export const supabase = createClient(url, anonKey, {
  auth: { persistSession: true, autoRefreshToken: true },
});
