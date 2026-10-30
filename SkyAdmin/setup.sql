-- سكاي البسيط — خادم مفاتيح التفعيل
-- Supabase ← SQL Editor ← New query ← الصق هذا الملف كاملاً ← Run. يمكن تشغيله أكثر من مرة بأمان.

create table if not exists public.licenses (
  key           text primary key,
  duration_days integer not null check (duration_days > 0),
  note          text not null default '',
  status        text not null default 'active' check (status in ('active', 'revoked')),
  hwid          text,
  created_at    timestamptz not null default now(),
  activated_at  timestamptz,
  expires_at    timestamptz,
  last_ip       text,
  last_seen     timestamptz,
  app_version   text,
  checks        integer not null default 0
);

-- لا أحد يقرأ الجدول أو يعدّله مباشرة إلا المفتاح السري (لوحة التحكم)
alter table public.licenses enable row level security;
revoke all on public.licenses from anon, authenticated;

-- يستدعيها برنامج المستخدم عند التفعيل وكل نصف ساعة: أول جهاز يفعّل المفتاح يُربط به للأبد
create or replace function public.activate_license(p_key text, p_hwid text, p_version text default '')
returns json
language plpgsql
security definer
set search_path = public
as $$
declare
  r   public.licenses;
  hdr json;
  ip  text;
begin
  if p_key is null or p_hwid is null or length(p_hwid) < 16 then
    return json_build_object('ok', false, 'error', 'invalid');
  end if;

  begin
    hdr := nullif(current_setting('request.headers', true), '')::json;
  exception when others then
    hdr := null;
  end;
  ip := trim(split_part(coalesce(hdr->>'cf-connecting-ip', hdr->>'x-forwarded-for', hdr->>'x-real-ip', ''), ',', 1));

  select * into r from public.licenses where key = upper(trim(p_key)) for update;
  if not found then
    return json_build_object('ok', false, 'error', 'invalid');
  end if;
  if r.status = 'revoked' then
    return json_build_object('ok', false, 'error', 'revoked');
  end if;

  if r.hwid is null then
    -- المدة تبدأ من لحظة التفعيل، لا من لحظة إنشاء المفتاح
    update public.licenses
       set hwid = p_hwid, activated_at = now(), expires_at = now() + make_interval(days => r.duration_days)
     where key = r.key
    returning * into r;
  elsif r.hwid <> p_hwid then
    return json_build_object('ok', false, 'error', 'other_device');
  end if;

  if r.expires_at <= now() then
    return json_build_object('ok', false, 'error', 'expired', 'expires_at', r.expires_at);
  end if;

  update public.licenses
     set last_ip = nullif(ip, ''), last_seen = now(), app_version = left(coalesce(p_version, ''), 20),
         checks = checks + 1
   where key = r.key;
  return json_build_object('ok', true, 'expires_at', r.expires_at, 'server_time', now());
end;
$$;

-- تمديد مفتاح (للوحة التحكم فقط): غير المفعّل تزيد مدته، والمفعّل يُمدد من تاريخ انتهائه أو من الآن إن كان منتهياً
create or replace function public.admin_extend(p_key text, p_days integer)
returns public.licenses
language plpgsql
security definer
set search_path = public
as $$
declare
  r public.licenses;
begin
  update public.licenses
     set duration_days = case when hwid is null then duration_days + p_days else duration_days end,
         expires_at    = case when hwid is null then null
                              else greatest(expires_at, now()) + make_interval(days => p_days) end
   where key = p_key
  returning * into r;
  return r;
end;
$$;

revoke all on function public.activate_license(text, text, text) from public;
grant execute on function public.activate_license(text, text, text) to anon, authenticated;
revoke all on function public.admin_extend(text, integer) from public, anon, authenticated;
grant execute on function public.admin_extend(text, integer) to service_role;
