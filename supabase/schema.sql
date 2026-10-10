-- V0.4 online rooms backend for Supabase
create extension if not exists pgcrypto;

create table if not exists public.game_rooms (
  code text primary key,
  host_player_id uuid not null,
  dealer_player_id uuid,
  phase text not null default 'lobby' check (phase in ('lobby','allocation','choosing','results')),
  current_round integer not null default 0,
  total_rounds integer not null default 0,
  allocation_deadline timestamptz,
  choice_deadline timestamptz,
  created_at timestamptz not null default now()
);
alter table public.game_rooms add column if not exists dealer_player_id uuid;
create table if not exists public.game_players (
  id uuid primary key,
  room_code text not null references public.game_rooms(code) on delete cascade,
  token uuid not null,
  nickname text not null check (char_length(nickname) between 1 and 24),
  seat_order integer not null,
  score integer not null default 0,
  area text check (area in ('A','B')),
  choice text check (choice in ('finger','thumb')),
  joined_at timestamptz not null default now(),
  unique(room_code,seat_order),
  unique(room_code,nickname)
);
create index if not exists game_players_room_order_idx on public.game_players(room_code,seat_order);
alter table public.game_rooms enable row level security;
alter table public.game_players enable row level security;

create or replace function public.create_game_room(p_nickname text,p_player_id uuid)
returns jsonb language plpgsql security definer set search_path=public,pg_temp as $$
declare v_code text; v_token uuid:=gen_random_uuid();
begin
 if p_nickname is null or char_length(trim(p_nickname)) not between 1 and 24 then raise exception '暱稱需為 1–24 個字元'; end if;
 loop v_code:=upper(substr(replace(gen_random_uuid()::text,'-',''),1,6)); exit when not exists(select 1 from game_rooms where code=v_code); end loop;
 insert into game_rooms(code,host_player_id) values(v_code,p_player_id);
 insert into game_players(id,room_code,token,nickname,seat_order) values(p_player_id,v_code,v_token,trim(p_nickname),1);
 return jsonb_build_object('code',v_code,'player_id',p_player_id,'token',v_token);
end $$;

create or replace function public.join_game_room(p_code text,p_nickname text,p_player_id uuid)
returns jsonb language plpgsql security definer set search_path=public,pg_temp as $$
declare v_room game_rooms%rowtype; v_token uuid:=gen_random_uuid(); v_seat integer;
begin
 select * into v_room from game_rooms where code=upper(trim(p_code)) for update;
 if not found then raise exception '找不到這個房間'; end if;
 if v_room.phase<>'lobby' then raise exception '遊戲已開始，暫時不能加入'; end if;
 if p_nickname is null or char_length(trim(p_nickname)) not between 1 and 24 then raise exception '暱稱需為 1–24 個字元'; end if;
 if (select count(*) from game_players where room_code=v_room.code)>=10 then raise exception '房間最多 10 位玩家'; end if;
 if exists(select 1 from game_players where room_code=v_room.code and nickname=trim(p_nickname)) then raise exception '暱稱已被使用'; end if;
 select coalesce(max(seat_order),0)+1 into v_seat from game_players where room_code=v_room.code;
 insert into game_players(id,room_code,token,nickname,seat_order) values(p_player_id,v_room.code,v_token,trim(p_nickname),v_seat);
 return jsonb_build_object('code',v_room.code,'player_id',p_player_id,'token',v_token);
end $$;

create or replace function public.get_game_state(p_code text,p_player_id uuid,p_token uuid)
returns jsonb language plpgsql security definer set search_path=public,pg_temp as $$
declare r game_rooms%rowtype; me game_players%rowtype; ps jsonb;
begin
 select * into r from game_rooms where code=upper(trim(p_code)); if not found then raise exception '房間不存在'; end if;
 select * into me from game_players where room_code=r.code and id=p_player_id and token=p_token; if not found then raise exception '玩家驗證失敗'; end if;
 select coalesce(jsonb_agg(jsonb_build_object('id',p.id,'nickname',p.nickname,'seat_order',p.seat_order,'score',p.score,'area',p.area,'has_chosen',p.choice is not null,'choice',case when r.phase='results' then p.choice else null end) order by p.seat_order),'[]'::jsonb) into ps from game_players p where p.room_code=r.code;
 return jsonb_build_object('code',r.code,'phase',r.phase,'current_round',r.current_round,'total_rounds',r.total_rounds,'host_player_id',r.host_player_id,'dealer_player_id',r.dealer_player_id,'allocation_deadline',r.allocation_deadline,'choice_deadline',r.choice_deadline,'players',ps,'my_choice',me.choice,'my_area',me.area,'my_player_id',me.id);
end $$;

create or replace function public.start_game_round(p_code text,p_player_id uuid,p_token uuid)
returns jsonb language plpgsql security definer set search_path=public,pg_temp as $$
declare r game_rooms%rowtype; n integer;
begin
 select * into r from game_rooms where code=upper(trim(p_code)) for update; if not found then raise exception '房間不存在'; end if;
 if not exists(select 1 from game_players where room_code=r.code and id=p_player_id and token=p_token) then raise exception '玩家驗證失敗'; end if;
 if r.host_player_id<>p_player_id then raise exception '只有房主可以開始'; end if;
 select count(*) into n from game_players where room_code=r.code; if n<3 then raise exception '至少需要 3 位玩家'; end if;
 if r.phase not in ('lobby','results') then raise exception '目前回合尚未結束'; end if;
 if r.current_round>=n then raise exception '所有回合已完成，請重設整場'; end if;
 update game_rooms set phase='allocation',current_round=current_round+1,total_rounds=n,allocation_deadline=now()+interval '3 minutes',choice_deadline=null,dealer_player_id=(select id from game_players where room_code=r.code order by random() limit 1) where code=r.code;
 update game_players set area=null,choice=null where room_code=r.code;
 return jsonb_build_object('ok',true);
end $$;

create or replace function public.set_game_area(p_code text,p_player_id uuid,p_token uuid,p_target_player_id uuid,p_area text)
returns jsonb language plpgsql security definer set search_path=public,pg_temp as $$
declare r game_rooms%rowtype;
begin
 select * into r from game_rooms where code=upper(trim(p_code)) for update; if not found then raise exception '房間不存在'; end if;
 if not exists(select 1 from game_players where room_code=r.code and id=p_player_id and token=p_token) then raise exception '玩家驗證失敗'; end if;
 if r.dealer_player_id<>p_player_id then raise exception '只有本回合莊家可以分區'; end if;
 if r.phase<>'allocation' then raise exception '現在不是分區階段'; end if;
 if p_area not in ('A','B') then raise exception '區域無效'; end if;
 update game_players set area=p_area where room_code=r.code and id=p_target_player_id; if not found then raise exception '找不到玩家'; end if;
 return jsonb_build_object('ok',true);
end $$;

create or replace function public.start_game_choices(p_code text,p_player_id uuid,p_token uuid)
returns jsonb language plpgsql security definer set search_path=public,pg_temp as $$
declare r game_rooms%rowtype; n integer;
begin
 select * into r from game_rooms where code=upper(trim(p_code)) for update; if not found then raise exception '房間不存在'; end if;
 if not exists(select 1 from game_players where room_code=r.code and id=p_player_id and token=p_token) then raise exception '玩家驗證失敗'; end if;
 if r.dealer_player_id<>p_player_id then raise exception '只有本回合莊家可以開始選擇'; end if;
 if r.phase<>'allocation' then raise exception '現在不是分區階段'; end if;
 if exists(select 1 from game_players where room_code=r.code and area is null) then raise exception '請先分配所有玩家'; end if;
 select count(*) into n from game_players where room_code=r.code;
 update game_rooms set phase='choosing',choice_deadline=now()+case when n<=5 then interval '3 minutes' else interval '5 minutes' end where code=r.code;
 return jsonb_build_object('ok',true);
end $$;

create or replace function public.submit_game_choice(p_code text,p_player_id uuid,p_token uuid,p_choice text)
returns jsonb language plpgsql security definer set search_path=public,pg_temp as $$
begin
 if p_choice not in ('finger','thumb') then raise exception '選擇無效'; end if;
 update game_players p set choice=p_choice from game_rooms r where p.room_code=r.code and r.code=upper(trim(p_code)) and p.id=p_player_id and p.token=p_token and r.phase='choosing';
 if not found then raise exception '無法提交：請確認玩家驗證及遊戲階段'; end if;
 return jsonb_build_object('ok',true);
end $$;

create or replace function public.finish_game_round(p_code text,p_player_id uuid,p_token uuid)
returns jsonb language plpgsql security definer set search_path=public,pg_temp as $$
declare r game_rooms%rowtype; a record; f integer; t integer;
begin
 select * into r from game_rooms where code=upper(trim(p_code)) for update; if not found then raise exception '房間不存在'; end if;
 if not exists(select 1 from game_players where room_code=r.code and id=p_player_id and token=p_token) then raise exception '玩家驗證失敗'; end if;
 if r.dealer_player_id<>p_player_id then raise exception '只有本回合莊家可以結算'; end if;
 if r.phase<>'choosing' then raise exception '現在不是選擇階段'; end if;
 if exists(select 1 from game_players where room_code=r.code and choice is null) and now()<r.choice_deadline then raise exception '仍有人尚未選擇'; end if;
 for a in select distinct area from game_players where room_code=r.code loop
  select count(*) filter(where choice='finger'),count(*) filter(where choice='thumb') into f,t from game_players where room_code=r.code and area=a.area;
  if f+t>=3 and f<>t then
   if f<t then update game_players set score=score+1 where room_code=r.code and area=a.area and choice='finger';
   else update game_players set score=score+1 where room_code=r.code and area=a.area and choice='thumb'; end if;
  end if;
 end loop;
 update game_rooms set phase='results',choice_deadline=null where code=r.code;
 return jsonb_build_object('ok',true);
end $$;

create or replace function public.reset_game_room(p_code text,p_player_id uuid,p_token uuid,p_full_reset boolean default false)
returns jsonb language plpgsql security definer set search_path=public,pg_temp as $$
declare r game_rooms%rowtype;
begin
 select * into r from game_rooms where code=upper(trim(p_code)) for update; if not found then raise exception '房間不存在'; end if;
 if not exists(select 1 from game_players where room_code=r.code and id=p_player_id and token=p_token) then raise exception '玩家驗證失敗'; end if;
 if r.host_player_id<>p_player_id then raise exception '只有房主可以重設'; end if;
 update game_players set area=null,choice=null,score=case when p_full_reset then 0 else score end where room_code=r.code;
 if p_full_reset then update game_rooms set phase='lobby',current_round=0,total_rounds=0,allocation_deadline=null,choice_deadline=null where code=r.code;
 else update game_rooms set phase='allocation',allocation_deadline=now()+interval '3 minutes',choice_deadline=null where code=r.code; end if;
 return jsonb_build_object('ok',true);
end $$;

create or replace function public.kick_game_player(p_code text,p_player_id uuid,p_token uuid,p_target_player_id uuid)
returns jsonb language plpgsql security definer set search_path=public,pg_temp as $
declare r game_rooms%rowtype;
begin
 select * into r from game_rooms where code=upper(trim(p_code)) for update;
 if not found then raise exception '房間不存在'; end if;
 if not exists(select 1 from game_players where room_code=r.code and id=p_player_id and token=p_token) then raise exception '玩家驗證失敗'; end if;
 if r.host_player_id<>p_player_id then raise exception '只有房主可以踢出玩家'; end if;
 if r.phase not in ('lobby','results') then raise exception '遊戲進行中不能踢出玩家'; end if;
 if p_target_player_id=r.host_player_id then raise exception '不能踢出房主'; end if;
 delete from game_players where room_code=r.code and id=p_target_player_id;
 if not found then raise exception '找不到玩家'; end if;
 update game_rooms set total_rounds=(select count(*) from game_players where room_code=r.code) where code=r.code;
 return jsonb_build_object('ok',true);
end $;

revoke all on all tables in schema public from anon,authenticated;
grant usage on schema public to anon,authenticated;
grant execute on function public.create_game_room(text,uuid) to anon,authenticated;
grant execute on function public.join_game_room(text,text,uuid) to anon,authenticated;
grant execute on function public.get_game_state(text,uuid,uuid) to anon,authenticated;
grant execute on function public.start_game_round(text,uuid,uuid) to anon,authenticated;
grant execute on function public.set_game_area(text,uuid,uuid,uuid,text) to anon,authenticated;
grant execute on function public.start_game_choices(text,uuid,uuid) to anon,authenticated;
grant execute on function public.submit_game_choice(text,uuid,uuid,text) to anon,authenticated;
grant execute on function public.finish_game_round(text,uuid,uuid) to anon,authenticated;
grant execute on function public.reset_game_room(text,uuid,uuid,boolean) to anon,authenticated;
grant execute on function public.kick_game_player(text,uuid,uuid,uuid) to anon,authenticated;
