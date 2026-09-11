-- Dùng khi Python/thiết bị xác thực bằng PUBLISHABLE KEY (anon).
-- Dán toàn bộ vào Supabase: SQL Editor -> Run.
-- (Khuyến nghị an toàn hơn: dùng service_role key trong .env, khi đó không cần các policy này.)

-- devices: Python upsert thiết bị theo device_code
create policy "devices_select_anon" on devices for select to anon using (true);
create policy "devices_insert_anon" on devices for insert to anon with check (true);
create policy "devices_update_anon" on devices for update to anon using (true);

-- access_logs: Python ghi lịch sử nhận diện + frontend đọc để hiển thị Access History
create policy "access_logs_insert_anon" on access_logs for insert to anon with check (true);
create policy "access_logs_select_anon" on access_logs for select to anon using (true);

-- alerts: Python ghi cảnh báo + frontend đọc để hiển thị Alert Page
create policy "alerts_insert_anon" on alerts for insert to anon with check (true);
create policy "alerts_select_anon" on alerts for select to anon using (true);

-- face_profiles: register tool đọc (tìm face_name) + cập nhật status
create policy "face_profiles_select_anon" on face_profiles for select to anon using (true);
create policy "face_profiles_update_anon" on face_profiles for update to anon using (true);