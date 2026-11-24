import sqlite3

 # Connect to your database
conn = sqlite3.connect('copilot_cache.db')
cursor = conn.cursor()

 # Replace '1' with the actual ID of the row you want to delete
#row_id_to_delete = 146

#cursor.execute("DELETE FROM Query_Cache WHERE id = ?", (row_id_to_delete,))
cursor.execute("DELETE FROM Conversation_History")

#conn.commit()
#conn.close()

#print(f"Row {row_id_to_delete} successfully deleted!") 
print("All rows successfully deleted from Conversation_History!")

conn.commit()
conn.close()

