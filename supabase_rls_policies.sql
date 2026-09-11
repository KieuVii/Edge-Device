-- Dung khi Python/thiet bi xac thuc bang PUBLISHABLE KEY (anon).
-- Dan toan bo vao Supabase: SQL Editor -> Run.
-- (Khuyen nghi an toan hon: dung service_role key trong .env, khi do khong can cac policy nay.)

-- devices: Python upsert thiet bi theo device_code
drop policy if exists "devices_select_anon" on devices;
create policy "devices_select_anon" on devices for select to anon using (true);
drop policy if exists "devices_insert_anon" on devices;
create policy "devices_insert_anon" on devices for insert to anon with check (true);
drop policy if exists "devices_update_anon" on devices;
create policy "devices_update_anon" on devices for update to anon using (true);

-- access_logs: Python ghi lich su nhan dien + frontend doc de hien thi Access History
drop policy if exists "access_logs_insert_anon" on access_logs;
create policy "access_logs_insert_anon" on access_logs for insert to anon with check (true);
drop policy if exists "access_logs_select_anon" on access_logs;
create policy "access_logs_select_anon" on access_logs for select to anon using (true);

-- alerts: Python ghi canh bao + frontend doc de hien thi Alert Page
drop policy if exists "alerts_insert_anon" on alerts;
create policy "alerts_insert_anon" on alerts for insert to anon with check (true);
drop policy if exists "alerts_select_anon" on alerts;
create policy "alerts_select_anon" on alerts for select to anon using (true);

-- face_profiles: register tool doc (tim face_name) + cap nhat status
drop policy if exists "face_profiles_select_anon" on face_profiles;
create policy "face_profiles_select_anon" on face_profiles for select to anon using (true);
drop policy if exists "face_profiles_update_anon" on face_profiles;
create policy "face_profiles_update_anon" on face_profiles for update to anon using (true);

-- device_commands: Python (anon) poll lenh start_register_face + cap nhat trang thai;
-- frontend (authenticated, admin) insert da co trong schema.sql (device_commands_admin_all)
drop policy if exists "device_commands_select_anon" on device_commands;
create policy "device_commands_select_anon" on device_commands for select to anon using (true);
drop policy if exists "device_commands_update_anon" on device_commands;
create policy "device_commands_update_anon" on device_commands for update to anon using (true);