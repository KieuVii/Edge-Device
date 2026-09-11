-- MIGRATION: Checkin/Checkout + remote commands
-- Chay toan bo trong Supabase: SQL Editor -> Run. (Idempotent - chay lai khong loi.)

-- 1. access_logs: them cot access_type (checkin/checkout), NULL = hoat dong mo cua thong thuong
alter table public.access_logs
  add column if not exists access_type text
  check (access_type in ('checkin', 'checkout'));

-- 2. device_commands: cho phep lenh start_checkin / start_checkout / restart_service
alter table public.device_commands
  drop constraint if exists device_commands_command_check;
alter table public.device_commands
  add constraint device_commands_command_check
  check (command in (
    'manual_unlock',
    'lock_door',
    'restart_camera',
    'start_register_face',
    'sync_face_db',
    'start_checkin',
    'start_checkout',
    'restart_service'
  ));