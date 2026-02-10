import { createClient } from '@supabase/supabase-js'

const supabaseUrl = "https://fhqiewinlrphsaottdwe.supabase.co"
const supabaseAnonKey = "sb_publishable_bqccpo7V4lW_80gLJlcpaA_enoJKY1q"

export const supabase = createClient(
  supabaseUrl,
  supabaseAnonKey
)
