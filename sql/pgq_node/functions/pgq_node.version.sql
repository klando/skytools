
create or replace function pgq_node.version()
returns text as $$
begin
    return '3.0.0.12';
end;
$$ language plpgsql;

